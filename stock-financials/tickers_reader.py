"""Read ticker symbols from local Stocks.xlsx."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import DATA_START_ROW, STOCKS_SHEET, STOCKS_XLSX, TICKER_COLUMN


def _normalize_symbol(raw: str) -> str | None:
    text = str(raw).strip().upper()
    if not text or text in ("TICKER", "SYMBOL", "STOCK", "NAN"):
        return None
    symbol = re.sub(r"\.(US|L|LON|SW|PA)$", "", text, flags=re.I)
    symbol = symbol.replace(" ", "")
    return symbol or None


def read_tickers(path: Path | None = None) -> list[str]:
    """Load tickers from Stocks.xlsx (column A by default, skip header row)."""
    file_path = path or STOCKS_XLSX
    if not file_path.exists():
        raise FileNotFoundError(
            f"Stocks workbook not found: {file_path}\n"
            "Place your ticker list in Stocks.xlsx (one symbol per row in column A)."
        )

    df = pd.read_excel(
        file_path,
        sheet_name=STOCKS_SHEET or 0,
        header=None,
        usecols=[TICKER_COLUMN],
    )
    if df.empty:
        return []

    series = df.iloc[DATA_START_ROW:, 0]
    tickers: list[str] = []
    seen: set[str] = set()
    for value in series:
        if pd.isna(value):
            continue
        symbol = _normalize_symbol(value)
        if symbol and symbol not in seen:
            seen.add(symbol)
            tickers.append(symbol)
    return tickers
