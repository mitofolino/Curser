"""Folder layout and file naming: {ticker}/{ticker}_{date}_{statement_type}.xlsx"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from config import STATEMENT_YEARS

PORTFOLIO_SUMMARY_FILENAME = "portfolio_summary.xlsx"


def ticker_dir(root: Path, ticker: str) -> Path:
    return root / ticker


def period_to_date_str(period) -> str:
    parsed = period_to_date(period)
    return parsed.strftime("%Y-%m-%d") if parsed else str(period)[:10]


def period_to_date(period) -> date | None:
    if isinstance(period, datetime):
        return period.date()
    if isinstance(period, date):
        return period
    text = str(period).strip()
    if " " in text:
        text = text.split(" ")[0]
    text = text.replace("/", "-")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def period_within_statement_window(period, years: int | None = None) -> bool:
    """True if reporting period is within the last N years (default: STATEMENT_YEARS)."""
    years = STATEMENT_YEARS if years is None else years
    parsed = period_to_date(period)
    if parsed is None:
        return True
    cutoff = date.today() - timedelta(days=int(years * 365.25))
    return parsed >= cutoff


def statement_filename(ticker: str, period, statement_type: str, ext: str = "xlsx") -> str:
    """e.g. MSFT_2024-09-30_income_statement_annual.xlsx"""
    date_str = period_to_date_str(period)
    safe_type = re.sub(r"[^\w]+", "_", statement_type.strip()).strip("_")
    return f"{ticker}_{date_str}_{safe_type}.{ext}"


def overview_filename(ticker: str, ext: str = "xlsx") -> str:
    return statement_filename(ticker, date.today(), "company_overview", ext)


def etf_overview_filename(ticker: str, ext: str = "xlsx") -> str:
    return statement_filename(ticker, date.today(), "etf_overview", ext)


def sec_filing_date_from_accession(accession: str) -> str:
    """Derive approximate filing year from SEC accession folder name."""
    match = re.search(r"-(\d{2})-", accession)
    if match:
        return f"20{match.group(1)}-12-31"
    return date.today().strftime("%Y-%m-%d")


def sec_filename(
    ticker: str, accession: str, form: str, original_name: str
) -> str:
    """e.g. AZN_2024-12-31_20-F_primary-document.html"""
    filing_date = sec_filing_date_from_accession(accession)
    stem = Path(original_name).stem
    ext = Path(original_name).suffix or ".txt"
    safe_form = form.replace("-", "_")
    safe_stem = re.sub(r"[^\w]+", "_", stem).strip("_")
    return f"{ticker}_{filing_date}_{safe_form}_{safe_stem}{ext}"
