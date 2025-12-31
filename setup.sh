#!/usr/bin/env bash
set -euo pipefail

cd "$(cd -- "$(dirname -- "$0")" && pwd)"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source ./.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Setup complete. Run ./run.sh to start the app."
