"""Read-only authentication against the shared Mirgam SQLite Cloud database."""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from werkzeug.security import check_password_hash


logger = logging.getLogger(__name__)


class AccountDatabaseUnavailable(Exception):
    """The shared account database could not be reached or queried."""


class AccountDatabaseNotConfigured(Exception):
    """No server-side SQLite Cloud URL has been configured."""


class MirgamAccountVerifier:
    """Look up active Mirgam accounts without copying them into local SQLite."""

    def __init__(self, database_url: SecretStr | None) -> None:
        self._database_url = database_url
        self._engine: Engine | None = None
        self._engine_lock = Lock()

    def _get_engine(self) -> Engine:
        if self._database_url is None:
            raise AccountDatabaseNotConfigured
        if self._engine is None:
            with self._engine_lock:
                if self._engine is None:
                    try:
                        # Keep the SQLite Cloud beta dialect's default pool
                        # configuration; QueuePool-only tuning kwargs can fail
                        # during engine construction for this dialect.
                        self._engine = create_engine(
                            self._database_url.get_secret_value(),
                        )
                    except Exception as exc:
                        # Driver exceptions can include the full connection URL, so
                        # log only the exception class and never its representation.
                        logger.error("SQLite Cloud engine initialization failed (error_type=%s)", type(exc).__name__)
                        raise AccountDatabaseUnavailable from None
        return self._engine

    def verify(self, identifier: str, password: str) -> dict[str, Any] | None:
        """Return public account fields only when credentials match an active row."""
        engine = self._get_engine()
        try:
            with engine.connect() as connection:
                account = connection.execute(
                    text(
                        """
                        SELECT id, name, username, password_hash
                        FROM accounts
                        WHERE is_active = 1 AND (name = :identifier OR username = :identifier)
                        ORDER BY CASE WHEN name = :identifier THEN 0 ELSE 1 END
                        LIMIT 1
                        """
                    ),
                    {"identifier": identifier},
                ).mappings().first()
        except Exception as exc:
            # SQLAlchemy and driver exception strings may contain the API key.
            logger.error("SQLite Cloud account lookup failed (error_type=%s)", type(exc).__name__)
            raise AccountDatabaseUnavailable from None

        if account is None:
            return None
        try:
            valid_password = check_password_hash(str(account["password_hash"]), password)
        except Exception:
            valid_password = False
        if not valid_password:
            return None

        return {
            "account_id": int(account["id"]),
            "farm_name": str(account["name"]),
            "username": str(account["username"]) if account["username"] is not None else None,
        }

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
