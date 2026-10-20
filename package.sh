#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NAME=$(basename "$ROOT")
OUT=${1:-"$(dirname "$ROOT")/${NAME}.zip"}

# Never ship interpreter caches or local development/release artifacts.
find "$ROOT" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$ROOT" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -f "$OUT"

cd "$(dirname "$ROOT")"
zip -qr "$OUT" "$NAME" \
  -x '*/.git/*' '*/__pycache__/*' '*.pyc' '*.pyo' '*.DS_Store' \
     '*.log' '*.bak' '*.bak-*' '*.zip'

echo "$OUT"
