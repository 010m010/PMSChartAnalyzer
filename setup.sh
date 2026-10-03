#!/usr/bin/env bash
set -euo pipefail

cd "$(cd -- "$(dirname -- "$0")" && pwd)"

requirements_file="requirements.txt"
if [ "$#" -gt 1 ]; then
    echo "Usage: ./setup.sh [--dev]" >&2
    exit 2
fi
case "${1:-}" in
    --dev) requirements_file="requirements-dev.txt" ;;
    "") ;;
    *) echo "Usage: ./setup.sh [--dev]" >&2; exit 2 ;;
esac

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

./.venv/bin/python -m pip install -r "$requirements_file"

echo "Setup complete. Run ./run.sh to start the app."
if [ "${1:-}" = "--dev" ]; then
    echo "Run ./.venv/bin/python scripts/check.py to check the project."
fi
