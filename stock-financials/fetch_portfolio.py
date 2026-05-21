#!/usr/bin/env python3
"""Fetch broker positions and update portfolio_summary.numbers (portfolio sheet only)."""

from __future__ import annotations

import logging
import sys

from config import PORTFOLIO_NUMBERS_PATH, PORTFOLIO_OUTPUT, PORTFOLIO_SHEET_NAME
from numbers_export import update_portfolio_sheet_only
from portfolio_positions import build_portfolio_dataframe
from portfolio_summary import _save_summary_xlsx

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

    mode = PORTFOLIO_OUTPUT
    if mode in ("numbers", "both"):
        update_portfolio_sheet_only(
            PORTFOLIO_NUMBERS_PATH,
            portfolio_df,
            portfolio_sheet=PORTFOLIO_SHEET_NAME,
        )
    if mode in ("xlsx", "both"):
        import pandas as pd

        _save_summary_xlsx(pd.DataFrame(), portfolio_df)

    logger.info("Portfolio updated: %d position(s)", len(portfolio_df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
