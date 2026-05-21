#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
LOG="output/update_numbers.log"
mkdir -p output
{
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') UTC ==="
  python update_numbers.py
  echo "EXIT_CODE=$?"
} > "$LOG" 2>&1
