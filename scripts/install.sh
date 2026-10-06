#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cd "$PROJECT_ROOT"
if [[ ! -x "$PROJECT_UV" ]]; then
  python3 -m pip install --isolated --no-cache-dir --target "$SHARED_TOOLS_ROOT/.runtime/tools" uv==0.8.22
fi
"$PROJECT_UV" python install 3.11.13
if [[ ! -d "$PROJECT_VENV" ]]; then
  "$PROJECT_UV" venv --python 3.11.13 --seed "$PROJECT_VENV"
fi
if [[ -f requirements.lock ]]; then
  "$PROJECT_UV" pip sync --python "$PROJECT_PYTHON" requirements.lock
else
  "$PROJECT_UV" pip install --python "$PROJECT_PYTHON" -r requirements.txt
fi
"$PROJECT_PYTHON" scripts/download_model.py
