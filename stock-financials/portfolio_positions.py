"""Merge live positions from eToro and IBKR into the portfolio sheet."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config import OUTPUT_DIR, PORTFOLIO_NUMBERS_PATH, PORTFOLIO_SHEET_NAME
from layout import PORTFOLIO_SUMMARY_FILENAME

logger = logging.getLogger(__name__)

PORTFOLIO_COLUMNS = [
    "Ticker",
    "Full Name",
    "Source",
    "Currency",
    "Shares",
    "Open Date",
    "Buy Price",
    "Total Fees",
]


def _empty_portfolio_df() -> pd.DataFrame:
    return pd.DataFrame(columns=PORTFOLIO_COLUMNS)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {col: row.get(col) for col in PORTFOLIO_COLUMNS}


def _align_template_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    lower_map = {c.strip().lower(): c for c in df.columns}
    for target in PORTFOLIO_COLUMNS:
        key = target.lower()
        if key in lower_map:
            rename[lower_map[key]] = target
    out = df.rename(columns=rename)
    for col in PORTFOLIO_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[PORTFOLIO_COLUMNS]


def read_portfolio_template(path: Path | None = None) -> pd.DataFrame | None:
    """
    Load header + example row from portfolio_summary.numbers (or .xlsx export).
    Returns None if the file is missing or unreadable.
    """
    path = path or PORTFOLIO_NUMBERS_PATH
    if not path.exists():
        return None

    suffix = path.suffix.lower()
    if suffix == ".numbers":
        try:
            from numbers_parser import Document
        except ImportError:
            logger.warning(
                "numbers-parser not installed; cannot read %s", path
            )
            return None
        try:
            doc = Document(path)
        except OSError as e:
            logger.warning("Cannot read %s: %s", path, e)
            return None
        for sheet in doc.sheets:
            for table in sheet.tables:
                if table.num_rows < 2:
                    continue
                headers = [
                    str(table.cell(0, c).value or "").strip()
                    for c in range(table.num_cols)
                ]
                if "Ticker" not in headers and "ticker" not in [
                    h.lower() for h in headers
                ]:
                    continue
                rows = []
                for r in range(1, table.num_rows):
                    values = [
                        table.cell(r, c).value for c in range(table.num_cols)
                    ]
                    if not any(v is not None and str(v).strip() for v in values):
                        continue
                    row = {
                        headers[c]: values[c]
                        for c in range(len(headers))
                        if headers[c]
                    }
                    rows.append(row)
                if rows:
                    return pd.DataFrame(rows)
        return None

    if suffix in (".xlsx", ".xlsm"):
        try:
            xl = pd.ExcelFile(path)
            sheet = (
                PORTFOLIO_SHEET_NAME
                if PORTFOLIO_SHEET_NAME in xl.sheet_names
                else xl.sheet_names[0]
            )
            df = pd.read_excel(path, sheet_name=sheet)
            if df.empty:
                return None
            return df
        except OSError as e:
            logger.warning("Cannot read %s: %s", path, e)
            return None

    return None


def fetch_all_positions() -> pd.DataFrame:
    """Fetch positions from enabled brokers; returns normalized DataFrame."""
    from brokers.etoro import fetch_etoro_positions
    from brokers.ibkr import fetch_ibkr_positions

    rows: list[dict[str, Any]] = []
    for fetcher, label in (
        (fetch_etoro_positions, "eToro"),
        (fetch_ibkr_positions, "IBKR"),
    ):
        try:
            batch = fetcher()
            rows.extend(batch)
            logger.info("%s: %d position(s)", label, len(batch))
        except Exception as e:
            logger.warning("%s positions skipped: %s", label, e)

    if not rows:
        return _empty_portfolio_df()

    normalized = [_normalize_row(r) for r in rows]
    return pd.DataFrame(normalized, columns=PORTFOLIO_COLUMNS)


def build_portfolio_dataframe() -> pd.DataFrame:
    """Live positions from eToro + IBKR APIs (or CSV fallbacks)."""
    return fetch_all_positions()


def portfolio_summary_path() -> Path:
    return OUTPUT_DIR / PORTFOLIO_SUMMARY_FILENAME
