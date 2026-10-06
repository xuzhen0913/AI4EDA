#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cd "$PROJECT_ROOT"
exec "$PROJECT_PYTHON" scripts/test_qwen.py
