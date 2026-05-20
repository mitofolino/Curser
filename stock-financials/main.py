#!/usr/bin/env python3
"""Read tickers from Google Sheets and download financial statements to Drive."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from config import (
    DOWNLOAD_10K,
    DRIVE_FOLDER_ID,
    LOCAL_OUTPUT_DIR,
    SEC_FILINGS_LIMIT,
)
from drive_upload import upload_file
from financials import download_sec_annual_filings, download_statements
from layout import (
    drive_statements_folder,
    sec_root_dir,
    sec_upload_subfolder,
    statements_dir,
    ticker_dir,
)
from portfolio_summary import TickerResult, save_and_upload_summary
from sheets_reader import read_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def process_ticker(
    ticker: str,
    *,
    local_root: Path,
    upload: bool,
    skip_drive: bool,
) -> TickerResult:
    result = TickerResult(ticker=ticker)
    root = ticker_dir(local_root, ticker)
    root.mkdir(parents=True, exist_ok=True)
    stmt_dir = statements_dir(local_root, ticker)

    path, overview, instrument = download_statements(ticker, stmt_dir)
    if path:
        result.ok = True
        result.overview = overview
        result.instrument_type = instrument
        result.has_quarterly = bool(overview.get("has_quarterly"))
        result.statement_file = path.name
        if upload and not skip_drive:
            upload_file(path, DRIVE_FOLDER_ID, subfolder=drive_statements_folder(ticker))

    if DOWNLOAD_10K and path and instrument == "stock":
        sec_base = sec_root_dir(local_root, ticker)
        if sec_base.exists():
            shutil.rmtree(sec_base)
        sec_base.mkdir(parents=True, exist_ok=True)
        paths, form = download_sec_annual_filings(ticker, sec_base, SEC_FILINGS_LIMIT)
        if paths and form:
            result.ok = True
            result.sec_form = form
            if upload and not skip_drive:
                for p in paths:
                    if p.is_file():
                        sub = sec_upload_subfolder(ticker, form, p, sec_base)
                        upload_file(p, DRIVE_FOLDER_ID, subfolder=sub)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        nargs="*",
        help="Override sheet: process only these symbols (e.g. AAPL MSFT)",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip Google Drive upload (save under LOCAL_OUTPUT_DIR only)",
    )
    parser.add_argument(
        "--no-10k",
        action="store_true",
        help="Skip SEC annual filings (10-K / 20-F)",
    )
    args = parser.parse_args()

    global DOWNLOAD_10K
    if args.no_10k:
        DOWNLOAD_10K = False

    if args.tickers:
        tickers = [t.upper().strip() for t in args.tickers]
    else:
        logger.info("Reading tickers from Google Sheet...")
        tickers = read_tickers()

    if not tickers:
        logger.error("No tickers found. Check SHEET_GID, TICKER_COLUMN, DATA_START_ROW in .env")
        return 1

    logger.info("Processing %d ticker(s): %s", len(tickers), ", ".join(tickers))
    LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[TickerResult] = []
    for ticker in tickers:
        try:
            results.append(
                process_ticker(
                    ticker,
                    local_root=LOCAL_OUTPUT_DIR,
                    upload=not args.local_only,
                    skip_drive=args.local_only,
                )
            )
        except Exception as e:
            logger.exception("%s: %s", ticker, e)
            results.append(TickerResult(ticker=ticker))

    save_and_upload_summary(results, upload=not args.local_only)

    success = [r.ticker for r in results if r.ok]
    failed = [r.ticker for r in results if not r.ok]
    logger.info("Done. OK: %s | Failed: %s", success, failed)
    logger.info("Local files: %s", LOCAL_OUTPUT_DIR.resolve())
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
