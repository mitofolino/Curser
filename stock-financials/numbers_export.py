"""Write summary + portfolio DataFrames to an Apple Numbers (.numbers) file."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import PORTFOLIO_DATA_START_ROW
from portfolio_positions import PORTFOLIO_COLUMNS

logger = logging.getLogger(__name__)

# 1-based row in Numbers → 0-based index
PORTFOLIO_HEADER_ROW = 0
PORTFOLIO_DATA_ROW_INDEX = PORTFOLIO_DATA_START_ROW - 1


def _cell_value(value) -> str | int | float | bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _write_dataframe(table, df: pd.DataFrame, *, data_start_row: int = 0) -> None:
    cols = list(df.columns)
    if data_start_row == 0:
        for c, name in enumerate(cols):
            table.write(0, c, name)
        data_start_row = 1
    for r in range(len(df)):
        out_row = data_start_row + r
        for c, name in enumerate(cols):
            table.write(out_row, c, _cell_value(df.iloc[r][name]))


def _header_column_map(table) -> dict[str, int]:
    """Map PORTFOLIO_COLUMNS to column index from row 1 headers."""
    mapping: dict[str, int] = {}
    for c in range(table.num_cols):
        raw = table.cell(PORTFOLIO_HEADER_ROW, c).value
        if raw is None:
            continue
        header = str(raw).strip()
        for col in PORTFOLIO_COLUMNS:
            if header.lower() == col.lower():
                mapping[col] = c
    for i, col in enumerate(PORTFOLIO_COLUMNS):
        mapping.setdefault(col, i)
    return mapping


def _clear_data_rows(table, start_row: int) -> None:
    for r in range(start_row, table.num_rows):
        for c in range(table.num_cols):
            table.write(r, c, "")


def _write_portfolio_table(table, df: pd.DataFrame) -> None:
    """Keep row 1 headers; write positions from row 2 onward."""
    col_map = _header_column_map(table)

    if not any(table.cell(PORTFOLIO_HEADER_ROW, c).value for c in range(table.num_cols)):
        for col, idx in col_map.items():
            table.write(PORTFOLIO_HEADER_ROW, idx, col)

    _clear_data_rows(table, PORTFOLIO_DATA_ROW_INDEX)

    for r in range(len(df)):
        out_row = PORTFOLIO_DATA_ROW_INDEX + r
        for col in PORTFOLIO_COLUMNS:
            if col not in df.columns:
                continue
            table.write(out_row, col_map[col], _cell_value(df.iloc[r][col]))


def _sheet_by_name(doc, name: str):
    for sheet in doc.sheets:
        if sheet.name == name:
            return sheet
    return None


def _upsert_summary_sheet(doc, name: str, df: pd.DataFrame) -> None:
    sheet = _sheet_by_name(doc, name)
    if sheet is None:
        doc.add_sheet(name)
        sheet = _sheet_by_name(doc, name)
    if sheet is None:
        raise RuntimeError(f"Could not create Numbers sheet: {name}")

    rows = max(len(df) + 1, 2)
    cols = max(len(df.columns), 1)
    if sheet.tables:
        table = sheet.tables[0]
    else:
        table = sheet.add_table(
            "Data",
            num_rows=rows,
            num_cols=cols,
            num_header_rows=1,
            num_header_cols=0,
        )
    _write_dataframe(table, df, data_start_row=0)


def _upsert_portfolio_sheet(doc, name: str, df: pd.DataFrame) -> None:
    sheet = _sheet_by_name(doc, name)
    if sheet is None:
        doc.add_sheet(name)
        sheet = _sheet_by_name(doc, name)
    if sheet is None:
        raise RuntimeError(f"Could not create Numbers sheet: {name}")

    min_rows = PORTFOLIO_DATA_ROW_INDEX + max(len(df), 1)
    min_cols = max(len(PORTFOLIO_COLUMNS), 1)
    if sheet.tables:
        table = sheet.tables[0]
    else:
        table = sheet.add_table(
            "Portfolio",
            num_rows=max(min_rows, 12),
            num_cols=min_cols,
            num_header_rows=1,
            num_header_cols=0,
        )
    _write_portfolio_table(table, df)


def update_portfolio_sheet_only(
    path: Path,
    portfolio_df: pd.DataFrame,
    *,
    portfolio_sheet: str = "portfolio",
) -> Path:
    """Update only the portfolio table; leave other sheets unchanged."""
    from numbers_parser import Document

    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Numbers file not found: {path}")

    doc = Document(path)
    _upsert_portfolio_sheet(doc, portfolio_sheet, portfolio_df)
    doc.save(path)
    logger.info(
        "Updated %s sheet '%s' with %d row(s) from row %d",
        path,
        portfolio_sheet,
        len(portfolio_df),
        PORTFOLIO_DATA_START_ROW,
    )
    return path


def save_to_numbers(
    path: Path,
    *,
    summary_df: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    summary_sheet: str = "summary",
    portfolio_sheet: str = "portfolio",
) -> Path:
    """Create or update .numbers; portfolio data starts at row 2 by default."""
    from numbers_parser import Document

    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        doc = Document(path)
        logger.info("Updating Numbers file: %s", path)
    else:
        doc = Document()
        if doc.sheets:
            doc.sheets[0].name = summary_sheet
        logger.info("Creating Numbers file: %s", path)

    _upsert_summary_sheet(doc, summary_sheet, summary_df)
    _upsert_portfolio_sheet(doc, portfolio_sheet, portfolio_df)
    doc.save(path)
    return path
