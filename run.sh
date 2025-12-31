#!/usr/bin/env bash
set -euo pipefail

cd "$(cd -- "$(dirname -- "$0")" && pwd)"

source ./.venv/bin/activate
python main.py
