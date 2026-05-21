#!/usr/bin/env python3
"""Download financial statements and SEC filings to a local folder."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from config import (
    DATA_START_ROW,
    DOWNLOAD_10K,
    OUTPUT_DIR,
    SEC_FILINGS_LIMIT,
    STOCKS_XLSX,
    TICKER_COLUMN,
)
from financials import download_sec_annual_filings, download_statements
from layout import sec_filename, ticker_dir
from portfolio_summary import TickerResult, save_summary
from tickers_reader import read_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _ticker_has_exports(dest: Path) -> bool:
    return dest.is_dir() and any(dest.iterdir())


def _sec_primary_filings(dest: Path, ticker: str) -> list[Path]:
    return [
        p
        for p in dest.iterdir()
        if p.is_file()
        and p.name.startswith(f"{ticker}_")
        and "primary" in p.name.lower()
        and ("_10_K_" in p.name or "_20_F_" in p.name)
    ]


def _sec_filings_complete(dest: Path, ticker: str, limit: int) -> bool:
    return len(_sec_primary_filings(dest, ticker)) >= limit


def _sec_form_on_disk(dest: Path, ticker: str) -> str | None:
    names = [p.name for p in _sec_primary_filings(dest, ticker)]
    if any("_20_F_" in n for n in names):
        return "20-F"
    if any("_10_K_" in n for n in names):
        return "10-K"
    return None


def _accession_from_path(path: Path, form: str) -> str:
    parts = path.parts
    if form in parts:
        idx = parts.index(form)
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return path.parent.name


def _prepare_sec_files(
    ticker: str, form: str, raw_paths: list[Path], dest_dir: Path
) -> list[Path]:
    """Copy SEC downloads into ticker folder with {ticker}_{date}_{form}_{doc}.ext names."""
    prepared: list[Path] = []
    for src in raw_paths:
        if not src.is_file():
            continue
        accession = _accession_from_path(src, form)
        name = sec_filename(ticker, accession, form, src.name)
        dest = dest_dir / name
        if dest.exists():
            logger.info("%s: skip existing %s", ticker, name)
            continue
        shutil.copy2(src, dest)
        prepared.append(dest)
        logger.info("%s: prepared %s", ticker, name)
    return prepared


def process_ticker(ticker: str, *, output_root: Path) -> TickerResult:
    result = TickerResult(ticker=ticker)
    dest = ticker_dir(output_root, ticker)
    dest.mkdir(parents=True, exist_ok=True)

    paths, overview, instrument = download_statements(ticker, dest)
    if overview:
        result.overview = overview
        result.instrument_type = instrument
        result.has_quarterly = bool(overview.get("has_quarterly"))
    if paths:
        result.files_exported = len(paths)
    if paths or _ticker_has_exports(dest):
        result.ok = True

    if DOWNLOAD_10K and instrument == "stock":
        if _sec_filings_complete(dest, ticker, SEC_FILINGS_LIMIT):
            result.sec_form = _sec_form_on_disk(dest, ticker)
            logger.info(
                "%s: SEC filings already present (%d), skipping download",
                ticker,
                len(_sec_primary_filings(dest, ticker)),
            )
        else:
            sec_tmp = dest / ".sec_tmp"
            if sec_tmp.exists():
                shutil.rmtree(sec_tmp)
            sec_tmp.mkdir(parents=True, exist_ok=True)
            raw_paths, form = download_sec_annual_filings(
                ticker, sec_tmp, SEC_FILINGS_LIMIT
            )
            if raw_paths and form:
                sec_files = _prepare_sec_files(ticker, form, raw_paths, dest)
                shutil.rmtree(sec_tmp, ignore_errors=True)
                result.ok = True
                result.sec_form = form
                result.files_exported += len(sec_files)
            else:
                shutil.rmtree(sec_tmp, ignore_errors=True)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        nargs="*",
        help="Process only these symbols (default: read from Stocks.xlsx)",
    )
    parser.add_argument(
        "--no-10k",
        action="store_true",
        help="Skip SEC annual filings (10-K / 20-F)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove legacy statements/ and sec/ subfolders before run",
    )
    args = parser.parse_args()

    global DOWNLOAD_10K
    if args.no_10k:
        DOWNLOAD_10K = False

    if args.tickers:
        tickers = [t.upper().strip() for t in args.tickers]
    else:
        logger.info("Reading tickers from %s", STOCKS_XLSX)
        tickers = read_tickers()

    if not tickers:
        logger.error(
            "No tickers found. Check %s (TICKER_COLUMN=%s, DATA_START_ROW=%s)",
            STOCKS_XLSX,
            TICKER_COLUMN,
            DATA_START_ROW,
        )
        return 1

    logger.info("Processing %d ticker(s): %s", len(tickers), ", ".join(tickers))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.cleanup:
        from cleanup import cleanup_local_output

        cleanup_local_output()

    results: list[TickerResult] = []
    for ticker in tickers:
        try:
            results.append(process_ticker(ticker, output_root=OUTPUT_DIR))
        except Exception as e:
            logger.exception("%s: %s", ticker, e)
            results.append(TickerResult(ticker=ticker))

    save_summary(results)

    success = [r.ticker for r in results if r.ok]
    failed = [r.ticker for r in results if not r.ok]
    logger.info("Done. OK: %s | Failed: %s", success, failed)
    logger.info("Output: %s", OUTPUT_DIR.resolve())
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
