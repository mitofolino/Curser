#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python fetch_portfolio.py
echo ""
read -p "Press Enter to close…"
