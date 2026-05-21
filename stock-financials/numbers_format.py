"""Column types and Numbers cell formatting from header units."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

# Numbers date/time directives (see numbers_parser.constants)
DATETIME_FORMAT_UTC = "yyyy-MM-dd HH:mm:ss"


@dataclass(frozen=True)
class ColumnFormat:
    kind: str  # text | number | currency | percentage | datetime
    decimal_places: int = 2
    currency_code: str | None = None
    thousands: bool = True


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def infer_column_format(header: str) -> ColumnFormat:
    """Infer Numbers format from display header (units in [brackets])."""
    h = header.lower()

    if "[utc]" in h or h.endswith(" date") or h.startswith("open date"):
        return ColumnFormat("datetime")

    if "[%]" in h:
        return ColumnFormat("percentage", decimal_places=2, thousands=False)

    if "eur→local" in h or "eur2" in h or (
        "exchange rate" in h and "open" in h
    ):
        return ColumnFormat("number", decimal_places=6, thousands=False)

    if "p/e" in h:
        return ColumnFormat("number", decimal_places=2, thousands=False)

    if "[eur]" in h or "(eur)" in h:
        return ColumnFormat("currency", currency_code="EUR", decimal_places=2)

    if "[local]" in h or h in (
        "price",
        "prices",
        "buy price",
        "total fees",
        "investment",
        "value",
    ):
        return ColumnFormat("number", decimal_places=2, thousands=True)

    if "[units]" in h or h == "shares":
        return ColumnFormat("number", decimal_places=4, thousands=True)

    if "update date" in h or h == "open date":
        return ColumnFormat("datetime")

    if "[ratio]" in h or "p/e" in h or "fx rate" in h:
        return ColumnFormat("number", decimal_places=4, thousands=False)

    if h in ("annual statements", "quarterly statements", "status"):
        return ColumnFormat("text")

    return ColumnFormat("text")


def _to_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_datetime(value: Any) -> datetime | None:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None)


def coerce_cell_value(value: Any, fmt: ColumnFormat) -> Any:
    """Coerce to a Numbers-friendly typed value (not display strings)."""
    if _is_blank(value):
        return ""

    if fmt.kind == "datetime":
        return _to_datetime(value) or ""

    if fmt.kind == "percentage":
        num = _to_float(value)
        if num is None:
            return ""
        # Stored as 12.5 meaning 12.5% → Numbers expects fraction
        return num / 100.0 if abs(num) > 1.5 else num

    if fmt.kind in ("number", "currency"):
        num = _to_float(value)
        if num is None:
            return ""
        return round(num, fmt.decimal_places)

    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).strip()


def _format_kwargs(fmt: ColumnFormat) -> tuple[str, dict[str, Any]]:
    if fmt.kind == "datetime":
        return "datetime", {"date_time_format": DATETIME_FORMAT_UTC}
    if fmt.kind == "currency" and fmt.currency_code:
        return "currency", {
            "currency": fmt.currency_code,
            "decimal_places": fmt.decimal_places,
            "show_thousands_separator": fmt.thousands,
        }
    if fmt.kind == "percentage":
        return "percentage", {
            "decimal_places": fmt.decimal_places,
            "show_thousands_separator": fmt.thousands,
        }
    if fmt.kind == "number":
        return "number", {
            "decimal_places": fmt.decimal_places,
            "show_thousands_separator": fmt.thousands,
        }
    return "text", {}


def apply_column_format(
    table,
    col: int,
    header: str,
    *,
    data_start_row: int,
    num_rows: int,
) -> None:
    """Apply inferred format to one column across data rows."""
    fmt = infer_column_format(header)
    if fmt.kind == "text":
        return
    format_name, kwargs = _format_kwargs(fmt)
    for r in range(num_rows):
        out_row = data_start_row + r
        try:
            table.set_cell_formatting(out_row, col, format_name, **kwargs)
        except (TypeError, IndexError, ValueError):
            pass


def apply_column_formats(
    table,
    df: pd.DataFrame,
    *,
    data_start_row: int,
    num_rows: int,
    col_map: dict[str, int] | None = None,
) -> None:
    """Apply per-column Number formats to data rows (not headers)."""
    for col_idx, header in enumerate(df.columns):
        header = str(header)
        fmt = infer_column_format(header)
        if fmt.kind == "text":
            continue
        out_col = col_map[header] if col_map and header in col_map else col_idx
        format_name, kwargs = _format_kwargs(fmt)
        for r in range(num_rows):
            out_row = data_start_row + r
            try:
                table.set_cell_formatting(out_row, out_col, format_name, **kwargs)
            except (TypeError, IndexError, ValueError):
                pass
