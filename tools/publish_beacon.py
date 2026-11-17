#!/usr/bin/env python3
"""Publish this beacon project to a new branch in a Git remote.

Example:
  python3 tools/publish_beacon.py --yes

The default destination is the remote repository root. The target branch's
tracked tree is replaced with the eligible source tree in a regular commit;
the branch history is preserved and no force push is used. Sensitive files and
generated firmware/build artifacts are excluded by path.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


DEFAULT_REPO = "https://github.com/yangjunwon1309/mirgam_mcp"
DEFAULT_BRANCH = "beacon"
GENERATED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    ".aws",
    ".codex",
    ".agents",
}
GENERATED_SUFFIXES = {
    ".a",
    ".bin",
    ".db",
    ".dylib",
    ".elf",
    ".map",
    ".o",
    ".pyc",
    ".so",
    ".sqlite",
    ".sqlite3",
}
SENSITIVE_EXACT = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "token",
    "tokens",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
}
SENSITIVE_PREFIXES = (
    ".env.",
    "secret.",
    "secrets.",
    "credential.",
    "credentials.",
    "id_rsa.",
    "id_ed25519.",
    "id_ecdsa.",
    "id_dsa.",
    "private_key",
    "private-key",
    "access_token",
    "refresh_token",
)
SENSITIVE_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
}


class PublishError(Exception):
    pass


def is_sensitive_path(relative: PurePosixPath) -> bool:
    for part in relative.parts:
        name = part.lower()
        if name in SENSITIVE_EXACT or name.startswith(SENSITIVE_PREFIXES):
            return True
        if name.endswith(tuple(SENSITIVE_SUFFIXES)):
            return True
    return False


def is_generated_path(relative: PurePosixPath) -> bool:
    if relative.name.lower() in GENERATED_DIRS:
        return True
    if any(part.lower() in GENERATED_DIRS for part in relative.parts[:-1]):
        return True
    if relative.name.lower() in {".ds_store", "thumbs.db"}:
        return True
    return relative.suffix.lower() in GENERATED_SUFFIXES


def collect_source_files(source: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    included: list[Path] = []
    skipped: list[tuple[str, str]] = []

    def on_walk_error(error: OSError) -> None:
        raise PublishError(f"cannot scan source tree: {error}")

    for current, dirnames, filenames in os.walk(source, topdown=True, followlinks=False, onerror=on_walk_error):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            path = current_path / dirname
            relative = PurePosixPath(path.relative_to(source).as_posix())
            if path.is_symlink():
                skipped.append((relative.as_posix(), "symlink"))
            elif is_sensitive_path(relative):
                skipped.append((relative.as_posix(), "sensitive path"))
            elif dirname.lower() in GENERATED_DIRS:
                skipped.append((relative.as_posix(), "generated or environment directory"))
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            path = current_path / filename
            relative = PurePosixPath(path.relative_to(source).as_posix())
            if path.is_symlink():
                skipped.append((relative.as_posix(), "symlink"))
            elif is_sensitive_path(relative):
                skipped.append((relative.as_posix(), "sensitive path"))
            elif is_generated_path(relative):
                skipped.append((relative.as_posix(), "generated artifact"))
            elif path.is_file():
                included.append(path)

    return included, skipped


def validate_remote_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme == "https":
        if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PublishError("repo URL must not contain embedded credentials, query parameters, or fragments")
        return
    if parsed.scheme == "ssh":
        if not parsed.netloc or parsed.username not in {None, "git"} or parsed.password or parsed.query or parsed.fragment:
            raise PublishError("SSH repo URL must use the normal git account and contain no embedded password")
        return
    if re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[A-Za-z0-9_./-]+(?:\.git)?", url):
        return
    raise PublishError("repo URL must be an https://, ssh://, or standard git@host:path URL")


def run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout_s: int = 120,
    capture: bool = False,
    echo_capture: bool = True,
) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            timeout=timeout_s,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
    except FileNotFoundError as error:
        raise PublishError("git executable was not found") from error
    except subprocess.TimeoutExpired as error:
        raise PublishError(f"git command timed out after {timeout_s}s: git {args[0]}") from error

    output = completed.stdout or "" if capture else ""
    if capture and echo_capture and output:
        print(output, end="" if output.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise PublishError(f"git {args[0]} failed with exit={completed.returncode}")
    return output


def safe_target_path(repo_root: Path, target_dir: PurePosixPath, relative: PurePosixPath) -> Path:
    candidate = repo_root.joinpath(*target_dir.parts, *relative.parts)
    resolved_root = repo_root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if not resolved_candidate.is_relative_to(resolved_root):
        raise PublishError(f"destination escapes the cloned repository: {target_dir / relative}")
    return candidate


def validate_target_dir(value: str) -> PurePosixPath:
    target = PurePosixPath(value or ".")
    if target.is_absolute() or any(part in {"..", ""} for part in target.parts):
        raise argparse.ArgumentTypeError("target directory must be a relative path without '..'")
    return target


def publish(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise PublishError("source must be a directory")
    validate_remote_url(args.repo_url)

    included, skipped = collect_source_files(source)
    if not included:
        raise PublishError("no eligible files found in source")

    print(f"source: {source}")
    print(f"branch: {args.branch}")
    print(f"destination: {args.target_dir.as_posix()}")
    print(f"eligible files: {len(included)}; excluded paths/artifacts: {len(skipped)}")
    for path, reason in skipped:
        print(f"excluded ({reason}): {path}")

    if args.dry_run:
        print("dry-run: no clone, commit, or push performed")
        return 0

    if not args.yes:
        try:
            answer = input(
                f"Replace the tracked file tree on branch '{args.branch}' with this source and push? [y/N] "
            ).strip().lower()
        except EOFError:
            print("cancelled (no interactive input)")
            return 0
        if answer not in {"y", "yes"}:
            print("cancelled")
            return 0

    run_git(["check-ref-format", "--branch", args.branch], timeout_s=15)
    temporary = Path(tempfile.mkdtemp(prefix="beacon-publish-"))
    checkout = temporary / "repo"
    try:
        run_git(["clone", "--origin", "origin", "--", args.repo_url, str(checkout)], timeout_s=args.timeout)

        branch_check = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", f"refs/heads/{args.branch}"],
            cwd=checkout,
            check=False,
            timeout=args.timeout,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if branch_check.returncode != 0:
            raise PublishError(f"cannot check remote branch (git ls-remote exit={branch_check.returncode})")
        branch_exists = bool(branch_check.stdout.strip())
        if branch_exists:
            run_git(
                ["switch", "--create", args.branch, "--track", f"origin/{args.branch}"],
                cwd=checkout,
                timeout_s=30,
            )
            print(f"replacing existing branch tree: origin/{args.branch}")
        else:
            run_git(["switch", "--create", args.branch], cwd=checkout, timeout_s=30)
            print(f"creating branch from the repository default branch: {args.branch}")

        # Remove every tracked path first so the branch contains only this source tree.
        run_git(["rm", "-r", "--ignore-unmatch", "--", "."], cwd=checkout, timeout_s=120)

        for source_file in included:
            relative = PurePosixPath(source_file.relative_to(source).as_posix())
            destination = safe_target_path(checkout, args.target_dir, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)

        run_git(["add", "--force", "--all", "--", "."], cwd=checkout, timeout_s=120)

        staged = run_git(
            ["diff", "--cached", "--name-only", "-z"],
            cwd=checkout,
            timeout_s=15,
            capture=True,
            echo_capture=False,
        )
        staged_names = [name for name in staged.split("\0") if name]
        staged_additions = run_git(
            ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"],
            cwd=checkout,
            timeout_s=15,
            capture=True,
            echo_capture=False,
        )
        unsafe_staged = [
            name for name in staged_additions.split("\0") if name and is_sensitive_path(PurePosixPath(name))
        ]
        if unsafe_staged:
            raise PublishError("sensitive-looking paths reached the Git index; refusing to commit")
        if not staged_names:
            raise PublishError("nothing changed compared with the remote branch")

        run_git(["commit", "-m", args.message], cwd=checkout, timeout_s=120)
        run_git(["push", "--set-upstream", "origin", args.branch], cwd=checkout, timeout_s=args.timeout)
        print(f"published replacement tree ({len(staged_names)} changed path(s)) to origin/{args.branch}")
    except Exception:
        if checkout.exists():
            print(f"publish worktree retained for recovery: {checkout}", file=sys.stderr)
        raise
    else:
        try:
            shutil.rmtree(temporary)
        except OSError as error:
            print(f"temporary worktree cleanup failed: {temporary}: {error}", file=sys.stderr)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace the beacon branch tree with eligible project files, commit, and push."
    )
    parser.add_argument("--repo-url", default=DEFAULT_REPO, help="Git remote URL (default: configured mirgam_mcp repository)")
    parser.add_argument("--source", default="/home/nano/beacon", help="source project directory")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="new remote branch name (default: beacon)")
    parser.add_argument("--target-dir", type=validate_target_dir, default=PurePosixPath("."), help="relative path in remote (default: repository root)")
    parser.add_argument("--message", default="Publish beacon project", help="commit message")
    parser.add_argument("--yes", action="store_true", help="skip the final confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="list included/excluded paths without cloning or pushing")
    parser.add_argument("--timeout", type=int, default=300, help="timeout in seconds for network Git operations")
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        return publish(parse_args(argv if argv is not None else sys.argv[1:]))
    except (PublishError, OSError, ValueError) as error:
        print(f"publish_beacon: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
