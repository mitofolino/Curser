#!/usr/bin/env python3
"""Refresh portfolio_summary.numbers summary + portfolio sheets (no full re-download)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, SEC_FILINGS_LIMIT, STOCKS_XLSX
from layout import ticker_dir
from main import _sec_form_on_disk, _ticker_has_exports
from portfolio_summary import TickerResult, save_summary
from tickers_reader import read_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _overview_from_xlsx(path: Path) -> dict:
    df = pd.read_excel(path)
    if "field" not in df.columns or "value" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        key = row.get("field")
        if key is None or (isinstance(key, float) and pd.isna(key)):
            continue
        val = row.get("value")
        if isinstance(val, float) and pd.isna(val):
            val = None
        out[str(key)] = val
    if "has_quarterly" in out:
        out["has_quarterly"] = bool(out["has_quarterly"])
    return out


def _load_ticker_result(ticker: str) -> TickerResult:
    result = TickerResult(ticker=ticker)
    dest = ticker_dir(OUTPUT_DIR, ticker)
    if not dest.is_dir():
        return result

    overview_paths = sorted(
        dest.glob(f"{ticker}_*_company_overview.xlsx"),
        reverse=True,
    )
    etf_paths = sorted(dest.glob(f"{ticker}_*_etf_overview.xlsx"), reverse=True)

    if etf_paths and (not overview_paths or etf_paths[0].stat().st_mtime >= overview_paths[0].stat().st_mtime):
        result.instrument_type = "etf"
        result.overview = _overview_from_xlsx(etf_paths[0])
    elif overview_paths:
        result.instrument_type = "stock"
        result.overview = _overview_from_xlsx(overview_paths[0])
        result.has_quarterly = bool(result.overview.get("has_quarterly"))

    result.sec_form = _sec_form_on_disk(dest, ticker)
    result.files_exported = len(list(dest.glob(f"{ticker}_*")))
    result.ok = bool(result.overview) or _ticker_has_exports(dest)
    return result


def main() -> int:
    logger.info("Reading tickers from %s", STOCKS_XLSX)
    tickers = read_tickers()
    if not tickers:
        logger.error("No tickers found in %s", STOCKS_XLSX)
        return 1

    results = [_load_ticker_result(t) for t in tickers]
    path = save_summary(results)
    logger.info(
        "Updated %s (summary: %d tickers, portfolio from brokers)",
        path,
        len(results),
    )
    ok = sum(1 for r in results if r.ok)
    logger.info("Summary rows OK: %d / %d", ok, len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
