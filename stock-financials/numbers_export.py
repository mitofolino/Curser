"""Write summary + portfolio DataFrames to an Apple Numbers (.numbers) file."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import PORTFOLIO_DATA_START_ROW
from numbers_format import (
    apply_column_format,
    apply_column_formats,
    apply_eur_currency_column_format,
    coerce_cell_value,
    copy_column_format_from_reference,
    infer_column_format,
)
from portfolio_formulas import apply_portfolio_formulas_numbers
from portfolio_positions import (
    PORTFOLIO_DISPLAY_NAMES,
    PORTFOLIO_EXPORT_COLUMNS,
    PORTFOLIO_SHEET_COL_INDEX,
    canonical_portfolio_header,
)

logger = logging.getLogger(__name__)

# 1-based row in Numbers → 0-based index
PORTFOLIO_HEADER_ROW = 0
PORTFOLIO_DATA_ROW_INDEX = PORTFOLIO_DATA_START_ROW - 1

# Column M / N (0-based): Price after Update Date, Value = Shares × Price
PORTFOLIO_PRICE_COL = 12
PORTFOLIO_VALUE_COL = 13
PORTFOLIO_EXCHANGE_RATE_COL = 14  # column O — current EUR→local
PORTFOLIO_VALUE_EUR_COL = 15  # column P — Value [EUR] = N / O


def _write_cell(table, row: int, col: int, value) -> None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        table.write(row, col, "")
        return
    table.write(row, col, value)


def _write_dataframe(table, df: pd.DataFrame, *, data_start_row: int = 0) -> None:
    cols = list(df.columns)
    header_row = 0 if data_start_row == 0 else data_start_row - 1
    first_data_row = 1 if data_start_row == 0 else data_start_row
    if data_start_row == 0:
        for c, name in enumerate(cols):
            table.write(header_row, c, name)
    formats = [infer_column_format(str(h)) for h in cols]
    for r in range(len(df)):
        out_row = first_data_row + r
        for c, name in enumerate(cols):
            raw = df.iloc[r][name]
            value = coerce_cell_value(raw, formats[c])
            _write_cell(table, out_row, c, value)
    apply_column_formats(
        table,
        df,
        data_start_row=first_data_row,
        num_rows=len(df),
    )


def _header_column_map(table, expected_columns: list[str]) -> dict[str, int]:
    """Map export column names to column index from row 1 headers."""
    aliases: dict[str, str] = {}
    for col in expected_columns:
        aliases[col.lower()] = col
    for internal, display in PORTFOLIO_DISPLAY_NAMES.items():
        aliases[internal.lower()] = display
        aliases[display.lower()] = display
    aliases["broker"] = PORTFOLIO_DISPLAY_NAMES["Source"]
    aliases["price"] = PORTFOLIO_DISPLAY_NAMES["Price"]
    aliases["prices"] = PORTFOLIO_DISPLAY_NAMES["Price"]
    aliases["value"] = PORTFOLIO_DISPLAY_NAMES["Value"]
    aliases["exchange rate"] = PORTFOLIO_DISPLAY_NAMES["Exchange Rate"]
    aliases["value [eur]"] = PORTFOLIO_DISPLAY_NAMES["Value EUR"]
    aliases["value (eur)"] = PORTFOLIO_DISPLAY_NAMES["Value EUR"]

    mapping: dict[str, int] = {}
    for c in range(table.num_cols):
        raw = table.cell(PORTFOLIO_HEADER_ROW, c).value
        if raw is None:
            continue
        header = str(raw).strip()
        key = aliases.get(header.lower()) or canonical_portfolio_header(header)
        if key:
            mapping[key] = c
    for i, col in enumerate(expected_columns):
        mapping.setdefault(col, i)
    for display, idx in PORTFOLIO_SHEET_COL_INDEX.items():
        if display in expected_columns:
            mapping[display] = idx
    return mapping


def _clear_data_rows(table, start_row: int) -> None:
    for r in range(start_row, table.num_rows):
        for c in range(table.num_cols):
            table.write(r, c, "")


def _write_canonical_headers(table) -> None:
    """Write row-1 headers with units at fixed column positions (N = Value [local], etc.)."""
    for display, col_idx in PORTFOLIO_SHEET_COL_INDEX.items():
        table.write(PORTFOLIO_HEADER_ROW, col_idx, display)


def _sync_portfolio_headers(
    table, col_map: dict[str, int], columns: list[str]
) -> None:
    """Write canonical headers with units (row 1) for all exported columns."""
    _write_canonical_headers(table)


def apply_portfolio_column_formats_numbers(
    path: Path,
    portfolio_df: pd.DataFrame,
    *,
    portfolio_sheet: str = "portfolio",
) -> None:
    """Re-apply formats after formulas (Value [EUR] matches Investment [EUR])."""
    from numbers_parser import Document

    if portfolio_df.empty:
        return

    path = path.expanduser()
    doc = Document(path)
    sheet = _sheet_by_name(doc, portfolio_sheet)
    if sheet is None or not sheet.tables:
        return

    table = sheet.tables[0]
    columns = list(portfolio_df.columns)
    col_map = _header_column_map(table, columns)
    num_rows = len(portfolio_df)
    _write_canonical_headers(table)

    for col in columns:
        if col in col_map:
            apply_column_format(
                table,
                col_map[col],
                col,
                data_start_row=PORTFOLIO_DATA_ROW_INDEX,
                num_rows=num_rows,
            )

    inv_eur = PORTFOLIO_DISPLAY_NAMES["Investment EUR"]
    val_eur = PORTFOLIO_DISPLAY_NAMES["Value EUR"]
    if inv_eur in col_map:
        apply_eur_currency_column_format(
            table,
            col_map[inv_eur],
            data_start_row=PORTFOLIO_DATA_ROW_INDEX,
            num_rows=num_rows,
        )
    if inv_eur in col_map and val_eur in col_map:
        if not copy_column_format_from_reference(
            table,
            ref_col=col_map[inv_eur],
            target_col=col_map[val_eur],
            data_start_row=PORTFOLIO_DATA_ROW_INDEX,
            num_rows=num_rows,
        ):
            apply_eur_currency_column_format(
                table,
                col_map[val_eur],
                data_start_row=PORTFOLIO_DATA_ROW_INDEX,
                num_rows=num_rows,
            )

    doc.save(path)
    logger.info("Applied portfolio column formats (%d row(s))", num_rows)


def _write_portfolio_table(table, df: pd.DataFrame) -> None:
    """Sync unit headers on row 1; write positions from row 2 onward."""
    columns = list(df.columns)
    col_map = _header_column_map(table, columns)
    _sync_portfolio_headers(table, col_map, columns)

    _clear_data_rows(table, PORTFOLIO_DATA_ROW_INDEX)

    formats = {col: infer_column_format(col) for col in columns}
    for r in range(len(df)):
        out_row = PORTFOLIO_DATA_ROW_INDEX + r
        for col in columns:
            if col not in col_map:
                continue
            value = coerce_cell_value(df.iloc[r][col], formats[col])
            _write_cell(table, out_row, col_map[col], value)
    apply_column_formats(
        table,
        df,
        data_start_row=PORTFOLIO_DATA_ROW_INDEX,
        num_rows=len(df),
        col_map=col_map,
    )
    value_header = PORTFOLIO_DISPLAY_NAMES["Value"]
    if value_header in df.columns:
        apply_column_format(
            table,
            col_map.get(value_header, PORTFOLIO_VALUE_COL),
            value_header,
            data_start_row=PORTFOLIO_DATA_ROW_INDEX,
            num_rows=len(df),
        )
    _write_price_column_m(table, df, col_map)


def _ticker_column(df: pd.DataFrame, col_map: dict[str, int]) -> str | None:
    for name in ("Ticker", PORTFOLIO_DISPLAY_NAMES["Ticker"]):
        if name in df.columns:
            return name
    for col in df.columns:
        if "ticker" in col.lower():
            return col
    return None


def _write_price_column_m(
    table, df: pd.DataFrame, col_map: dict[str, int]
) -> None:
    """Write current price to column M (Price [local]), matching template layout."""
    price_header = PORTFOLIO_DISPLAY_NAMES["Price"]
    price_col = col_map.get(price_header, PORTFOLIO_PRICE_COL)
    if price_header not in df.columns or df.empty:
        return

    price_fmt = infer_column_format(price_header)
    for r in range(len(df)):
        value = coerce_cell_value(df.iloc[r][PORTFOLIO_DISPLAY_NAMES["Price"]], price_fmt)
        if value == "":
            continue
        _write_cell(table, PORTFOLIO_DATA_ROW_INDEX + r, price_col, value)

    apply_column_format(
        table,
        price_col,
        PORTFOLIO_DISPLAY_NAMES["Price"],
        data_start_row=PORTFOLIO_DATA_ROW_INDEX,
        num_rows=len(df),
    )
    logger.info(
        "Wrote current prices to column M (%s) for %d row(s)",
        PORTFOLIO_DISPLAY_NAMES["Price"],
        len(df),
    )


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
    min_cols = max(len(df.columns), 1)
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
    apply_portfolio_formulas_numbers(
        path, portfolio_sheet=portfolio_sheet, num_data_rows=len(portfolio_df)
    )
    apply_portfolio_column_formats_numbers(
        path, portfolio_df, portfolio_sheet=portfolio_sheet
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
    apply_portfolio_formulas_numbers(
        path, portfolio_sheet=portfolio_sheet, num_data_rows=len(portfolio_df)
    )
    apply_portfolio_column_formats_numbers(
        path, portfolio_df, portfolio_sheet=portfolio_sheet
    )
    return path
