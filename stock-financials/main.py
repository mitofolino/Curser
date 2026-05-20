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
from financials import download_10k_filings, download_statements
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
) -> bool:
    ticker_dir = local_root / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    ok = False

    xlsx = download_statements(ticker, ticker_dir)
    if xlsx:
        ok = True
        if upload and not skip_drive:
            upload_file(xlsx, DRIVE_FOLDER_ID, subfolder=ticker)

    if DOWNLOAD_10K and xlsx and "etf_overview" not in xlsx.name:
        sec_dir = ticker_dir / "SEC_10-K"
        if sec_dir.exists():
            shutil.rmtree(sec_dir)
        sec_dir.mkdir(parents=True, exist_ok=True)
        paths = download_10k_filings(ticker, sec_dir, SEC_FILINGS_LIMIT)
        if paths:
            ok = True
            if upload and not skip_drive:
                for p in paths:
                    if p.is_file():
                        upload_file(p, DRIVE_FOLDER_ID, subfolder=f"{ticker}/SEC_10-K")

    return ok


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
        help="Skip SEC 10-K downloads",
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

    success, failed = [], []
    for ticker in tickers:
        try:
            if process_ticker(
                ticker,
                local_root=LOCAL_OUTPUT_DIR,
                upload=not args.local_only,
                skip_drive=args.local_only,
            ):
                success.append(ticker)
            else:
                failed.append(ticker)
        except Exception as e:
            logger.exception("%s: %s", ticker, e)
            failed.append(ticker)

    logger.info("Done. OK: %s | Failed: %s", success, failed)
    logger.info("Local files: %s", LOCAL_OUTPUT_DIR.resolve())
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
