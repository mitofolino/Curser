#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
LOG="output/fetch_portfolio.log"
mkdir -p output
{
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') UTC ==="
  python fetch_portfolio.py
  echo "EXIT_CODE=$?"
} > "$LOG" 2>&1
exit "${PIPESTATUS[0]:-$?}"
