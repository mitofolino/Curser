"""Consistent local and Google Drive folder layout per ticker."""

from __future__ import annotations

from pathlib import Path

FINANCIALS_XLSX = "financials.xlsx"
ETF_XLSX = "etf_overview.xlsx"
SUMMARY_SHEET_NAME = "Portfolio Summary"


def ticker_dir(root: Path, ticker: str) -> Path:
    return root / ticker


def statements_dir(root: Path, ticker: str) -> Path:
    return ticker_dir(root, ticker) / "statements"


def sec_root_dir(root: Path, ticker: str) -> Path:
    return ticker_dir(root, ticker) / "sec"


def drive_statements_folder(ticker: str) -> str:
    return f"{ticker}/statements"


def drive_sec_folder(ticker: str, form: str, relative_parent: Path) -> str:
    """e.g. AZN/sec/20-F/0001104659-24-025553"""
    parts = [ticker, "sec", form, *relative_parent.parts]
    return "/".join(parts)


def sec_upload_subfolder(ticker: str, form: str, file_path: Path, sec_base: Path) -> str:
    """Map SEC file to AZN/sec/20-F/{accession}/ on Drive."""
    rel = file_path.relative_to(sec_base)
    parts = list(rel.parts)
    if "sec-edgar-filings" in parts:
        idx = parts.index("sec-edgar-filings")
        parts = parts[idx + 1 :]
    if form in parts:
        idx = parts.index(form)
        folder_parts = parts[idx:-1]
        if folder_parts:
            return f"{ticker}/sec/{'/'.join(folder_parts)}"
    parent = file_path.parent.relative_to(sec_base)
    return f"{ticker}/sec/{parent}".as_posix()
