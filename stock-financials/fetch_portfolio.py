#!/usr/bin/env python3
"""Fetch broker positions and update portfolio_summary.numbers (portfolio sheet only)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import PORTFOLIO_NUMBERS_PATH, PORTFOLIO_OUTPUT, PORTFOLIO_SHEET_NAME
from numbers_export import update_portfolio_sheet_only
from portfolio_positions import build_portfolio_dataframe
from portfolio_summary import _save_summary_xlsx

_STAGING_CSV = Path(__file__).resolve().parent / "output" / "portfolio_positions.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _write_staging_csv(portfolio_df) -> Path:
    _STAGING_CSV.parent.mkdir(parents=True, exist_ok=True)
    portfolio_df.to_csv(_STAGING_CSV, index=False)
    logger.info("Staging CSV: %s (%d rows)", _STAGING_CSV, len(portfolio_df))
    return _STAGING_CSV


def main() -> int:
    portfolio_df = build_portfolio_dataframe()
    if portfolio_df.empty:
        logger.error("No positions returned. Check eToro/IBKR settings in .env")
        return 1

    _write_staging_csv(portfolio_df)

    mode = PORTFOLIO_OUTPUT
    try:
        if mode in ("numbers", "both"):
            update_portfolio_sheet_only(
                PORTFOLIO_NUMBERS_PATH,
                portfolio_df,
                portfolio_sheet=PORTFOLIO_SHEET_NAME,
            )
        if mode in ("xlsx", "both"):
            import pandas as pd

            _save_summary_xlsx(pd.DataFrame(), portfolio_df)
    except PermissionError:
        logger.error(
            "Cannot write %s from this environment (macOS privacy). "
            "Run in Terminal.app: cd %s && source .venv/bin/activate && python fetch_portfolio.py "
            "Or double-click update_portfolio.command",
            PORTFOLIO_NUMBERS_PATH,
            Path(__file__).resolve().parent,
        )
        return 2

    logger.info("Portfolio updated: %d position(s)", len(portfolio_df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
