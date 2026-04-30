#!/usr/bin/env bash
set -euo pipefail

echo "==> auto-cxas-scrapi install script"

PYTHON=$(which python3.11 2>/dev/null || which python3 2>/dev/null)
$PYTHON --version | grep -E "3\\.(11|12|13)" > /dev/null || {
  echo "ERROR: Python 3.11+ required. Found: $($PYTHON --version)"
  exit 1
}
echo "Using: $($PYTHON --version)"

if [ ! -d ".venv" ]; then
  $PYTHON -m venv .venv
  echo "Created .venv"
fi
source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example -- edit it before running."
fi

if command -v pre-commit &>/dev/null; then
  pre-commit install
  echo "pre-commit hooks installed."
fi

echo ""
echo "==> Done! Next steps:"
echo "  1. Edit .env -- set GOOGLE_CLOUD_PROJECT, AUTO_CXAS_APP_NAME, etc."
echo "  2. gcloud auth application-default login"
echo "  3. python evaluate.py --dry-run     # verify setup"
echo "  4. auto-cxas init"
echo "  5. auto-cxas daemon --dry-run       # run experiment loop"
