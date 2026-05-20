from __future__ import annotations

import re

from config import DATA_START_ROW, SHEET_GID, SPREADSHEET_ID, TICKER_COLUMN
from google_auth import sheets_service


def _sheet_title_for_gid(service, spreadsheet_id: str, gid: int) -> str:
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("sheetId") == gid:
            return props["title"]
    raise ValueError(f"No sheet with gid={gid} in spreadsheet {spreadsheet_id}")


def _column_letter(index: int) -> str:
    """0 -> A, 1 -> B, ..."""
    result = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def read_tickers() -> list[str]:
    service = sheets_service()
    title = _sheet_title_for_gid(service, SPREADSHEET_ID, SHEET_GID)
    col = _column_letter(TICKER_COLUMN)
    start_row = DATA_START_ROW + 1  # Sheets API is 1-based
    range_name = f"'{title}'!{col}{start_row}:{col}"

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=range_name)
        .execute()
    )
    rows = result.get("values", [])
    tickers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row:
            continue
        raw = str(row[0]).strip().upper()
        if not raw or raw in ("TICKER", "SYMBOL", "STOCK"):
            continue
        # Allow BRK.B style tickers; strip exchange suffixes like "AAPL.US"
        symbol = re.sub(r"\.(US|L|LON|SW|PA)$", "", raw, flags=re.I)
        symbol = symbol.replace(" ", "")
        if symbol and symbol not in seen:
            seen.add(symbol)
            tickers.append(symbol)
    return tickers
