#!/usr/bin/env python3
"""Fetch broker positions and update portfolio_summary.numbers (portfolio + summary)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import PORTFOLIO_NUMBERS_PATH
from portfolio_positions import build_portfolio_dataframe
from portfolio_summary import save_portfolio_and_summary

_STAGING_CSV = Path(__file__).resolve().parent / "output" / "portfolio_positions.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    portfolio_df = build_portfolio_dataframe()
    if portfolio_df.empty:
        logger.error("No positions returned. Check eToro/IBKR settings in .env")
        return 1

    _STAGING_CSV.parent.mkdir(parents=True, exist_ok=True)
    portfolio_df.to_csv(_STAGING_CSV, index=False)
    logger.info("Staging CSV: %s (%d rows)", _STAGING_CSV, len(portfolio_df))

    try:
        path, ticker_count, ok = save_portfolio_and_summary(portfolio_df=portfolio_df)
    except PermissionError:
        logger.error(
            "Cannot write %s from this environment (macOS privacy). "
            "Run in Terminal.app: cd %s && source .venv/bin/activate && python fetch_portfolio.py "
            "Or double-click update_portfolio.command",
            PORTFOLIO_NUMBERS_PATH,
            Path(__file__).resolve().parent,
        )
        return 2

    logger.info(
        "Updated %s — portfolio: %d row(s), summary: %d ticker(s) (%d OK)",
        path,
        len(portfolio_df),
        ticker_count,
        ok,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
