#!/usr/bin/env python3
"""Refresh portfolio_summary.numbers: portfolio from brokers + summary from holdings."""

from __future__ import annotations

import logging
import sys

from portfolio_summary import save_portfolio_and_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    path, ticker_count, ok = save_portfolio_and_summary()
    logger.info(
        "Updated %s (summary: %d distinct tickers, portfolio from brokers)",
        path,
        ticker_count,
    )
    logger.info("Summary rows OK: %d / %d", ok, ticker_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
