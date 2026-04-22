#!/usr/bin/env bash
# Start air-quality-be (FastAPI :8000)
# Usage: bash run.sh [--no-install]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SKIP_INSTALL=false
for arg in "$@"; do
  case "$arg" in
    --no-install) SKIP_INSTALL=true ;;
  esac
done

if [ ! -f .env ]; then
  echo "⚠️  .env chưa có — copy từ .env.example"
  cp .env.example .env
fi

if [ ! -d .venv ]; then
  echo ">>> Tạo Python venv..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [ "$SKIP_INSTALL" = false ]; then
  echo ">>> pip install -r requirements.txt..."
  pip install -q -r requirements.txt
fi

echo ">>> Starting FastAPI on :8000..."
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
