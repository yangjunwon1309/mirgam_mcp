#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec python3 services/model_runner/server.py
