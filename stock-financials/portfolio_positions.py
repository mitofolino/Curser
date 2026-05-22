"""Merge live positions from eToro and IBKR into the portfolio sheet."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config import OUTPUT_DIR, PORTFOLIO_NUMBERS_PATH, PORTFOLIO_SHEET_NAME
from fx_rates import (
    eur_to_local_rate_on_date,
    parse_open_date_for_fx,
    prefetch_rates_to_eur,
    prefetch_rates_to_eur_on_dates,
)
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
    "Investment",
    "Open Exchange Rate",
    "Investment EUR",
    "Update Date",
    "Price",
    "Value",
    "Exchange Rate",
    "Value EUR",
    "Total Return",
    "Stock Return",
    "Fee Influence",
    "Used Platform",
    "Position ID",
]

# Human-readable headers for Numbers / Excel (units in square brackets)
PORTFOLIO_DISPLAY_NAMES: dict[str, str] = {
    "Ticker": "Ticker",
    "Full Name": "Instrument Name",
    "Source": "Source",
    "Currency": "Currency",
    "Shares": "Shares [units]",
    "Open Date": "Open Date [UTC]",
    "Buy Price": "Buy Price [local]",
    "Total Fees": "Total Fees [local]",
    "Investment": "Investment [local]",
    "Open Exchange Rate": "Open Exchange Rate [EUR→local]",
    "Investment EUR": "Investment [EUR]",
    "Update Date": "Update Date [UTC]",
    "Price": "Price [local]",
    "Value": "Value [local]",
    "Exchange Rate": "Exchange Rate [EUR→local]",
    "Value EUR": "Value [EUR]",
    "Total Return": "Total Return [EUR]",
    "Stock Return": "Stock Return [EUR]",
    "Fee Influence": "Fee Influence [EUR]",
    "Used Platform": "Used Platform",
    "Position ID": "Position ID",
}

# Filled by Numbers/Excel formulas on export (see portfolio_formulas.py)
PORTFOLIO_FORMULA_COLUMNS = frozenset(
    {
        "Investment",
        "Investment EUR",
        "Value",
        "Value EUR",
        "Total Return",
        "Stock Return",
        "Fee Influence",
    }
)

PORTFOLIO_EXPORT_COLUMNS = [
    PORTFOLIO_DISPLAY_NAMES[c] for c in PORTFOLIO_COLUMNS
]

# Fixed 0-based column indices in portfolio Numbers table (row 1 = headers)
PORTFOLIO_SHEET_COL_INDEX: dict[str, int] = {
    PORTFOLIO_DISPLAY_NAMES[c]: i for i, c in enumerate(PORTFOLIO_COLUMNS)
}

_DISPLAY_TO_INTERNAL = {v: k for k, v in PORTFOLIO_DISPLAY_NAMES.items()}

# Sheet headers without units → internal column key
PORTFOLIO_LEGACY_HEADER_ALIASES: dict[str, str] = {
    "name": "Full Name",
    "instrument name": "Full Name",
    "shares": "Shares",
    "price": "Price",
    "prices": "Price",
    "value": "Value",
    "exchange rate": "Exchange Rate",
    "investment (eur)": "Investment EUR",
    "investment [eur]": "Investment EUR",
    "value (eur)": "Value EUR",
    "value [eur]": "Value EUR",
    "total return": "Total Return",
    "total return [eur]": "Total Return",
    "total return (eur)": "Total Return",
    "stock return": "Stock Return",
    "stock return [eur]": "Stock Return",
    "stock return (eur)": "Stock Return",
    "fee influence": "Fee Influence",
    "fee influence [eur]": "Fee Influence",
    "fee influence (eur)": "Fee Influence",
    "used platform": "Used Platform",
    "platform": "Used Platform",
    "position id": "Position ID",
    "positionid": "Position ID",
}


def canonical_portfolio_header(label: str) -> str | None:
    """Map any portfolio header (legacy or canonical) to display name with units."""
    if not label or not str(label).strip():
        return None
    key = str(label).strip().lower()
    if key in _DISPLAY_TO_INTERNAL:
        internal = _DISPLAY_TO_INTERNAL[key]
        return PORTFOLIO_DISPLAY_NAMES[internal]
    if key in PORTFOLIO_LEGACY_HEADER_ALIASES:
        internal = PORTFOLIO_LEGACY_HEADER_ALIASES[key]
        if internal in PORTFOLIO_DISPLAY_NAMES:
            return PORTFOLIO_DISPLAY_NAMES[internal]
    if "exchange rate" in key and "open" not in key:
        return PORTFOLIO_DISPLAY_NAMES["Exchange Rate"]
    if key in ("value [eur]", "value (eur)"):
        return PORTFOLIO_DISPLAY_NAMES["Value EUR"]
    if key in ("total return", "total return [eur]", "total return (eur)"):
        return PORTFOLIO_DISPLAY_NAMES["Total Return"]
    if key in ("stock return", "stock return [eur]", "stock return (eur)"):
        return PORTFOLIO_DISPLAY_NAMES["Stock Return"]
    if key in ("fee influence", "fee influence [eur]", "fee influence (eur)"):
        return PORTFOLIO_DISPLAY_NAMES["Fee Influence"]
    if key in ("used platform", "platform"):
        return PORTFOLIO_DISPLAY_NAMES["Used Platform"]
    if key in ("position id", "positionid"):
        return PORTFOLIO_DISPLAY_NAMES["Position ID"]
    for internal, display in PORTFOLIO_DISPLAY_NAMES.items():
        d = display.lower()
        if key == d or key.startswith(d.split("[")[0].strip().lower()):
            return display
        if "eur2" in key and internal == "Open Exchange Rate" and "open" in key:
            return display
        if "eur2" in key and internal == "Exchange Rate" and "open" not in key:
            return display
    return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _fmt_text(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _fmt_ticker(value: Any) -> str:
    return _fmt_text(value).upper()


def _fmt_source(value: Any) -> str:
    from market_source import normalize_market_source

    normalized = normalize_market_source(_fmt_text(value) or None)
    return normalized or ""


def _fmt_currency(value: Any) -> str:
    return _fmt_text(value).upper()


def _fmt_shares(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    places = 6 if abs(v) < 1 else 4
    return f"{v:.{places}f}".rstrip("0").rstrip(".")


def _fmt_price(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    places = 4 if abs(v) < 10 else 2
    return f"{v:.{places}f}".rstrip("0").rstrip(".")


def _fmt_fees(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_open_date_utc(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_open_date(value: Any) -> str:
    if _is_blank(value):
        return ""
    if isinstance(value, datetime):
        return _format_open_date_utc(value)
    if isinstance(value, date):
        return _format_open_date_utc(datetime.combine(value, datetime.min.time()))
    if isinstance(value, pd.Timestamp):
        return _format_open_date_utc(value.to_pydatetime())
    text = _fmt_text(value)
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        return _format_open_date_utc(datetime.fromisoformat(normalized))
    except ValueError:
        pass
    if len(text) >= 10 and text[4] == "-":
        return text[:10] + " 00:00:00" if len(text) == 10 else text[:19]
    return text


def _fmt_fx_rate(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _fmt_investment_placeholder(value: Any) -> str:
    """Formula columns: leave empty for Numbers/Excel to fill."""
    return ""


def _fmt_platform(value: Any) -> str:
    text = _fmt_text(value)
    if not text:
        return ""
    lower = text.lower()
    if lower in ("etoro", "e-toro"):
        return "eToro"
    if lower == "ibkr":
        return "IBKR"
    return text


def _fmt_position_id(value: Any) -> str:
    if _is_blank(value):
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


_IBKR_POSITION_ID_RE = re.compile(r"^([A-Za-z0-9]+):(\d+)$")


def _normalize_ibkr_position_id(position_id: str) -> str:
    """Canonical form: U18476088:559289446 (no float/scientific conId)."""
    pid = _fmt_position_id(position_id)
    if not pid:
        return ""
    m = _IBKR_POSITION_ID_RE.match(pid)
    if m:
        return f"{m.group(1).upper()}:{int(m.group(2))}"
    if pid.isdigit():
        return str(int(pid))
    return pid


def _position_id_lookup_keys(platform: str, position_id: Any) -> list[str]:
    """Keys used in preserved open-date map (account:conId + bare conId for IBKR)."""
    pid = _fmt_position_id(position_id)
    if not pid:
        return []
    if platform == "IBKR":
        norm = _normalize_ibkr_position_id(pid)
        keys = [norm] if norm else []
        if ":" in norm:
            keys.append(norm.split(":", 1)[1])
        elif norm.isdigit():
            keys.append(norm)
        return keys
    return [pid]


def _resolve_platform(platform: Any, position_id: Any) -> str:
    resolved = _fmt_platform(platform)
    if resolved:
        return resolved
    pid = _fmt_position_id(position_id)
    if pid and _IBKR_POSITION_ID_RE.match(pid):
        return "IBKR"
    return ""


def _to_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _portfolio_raw_to_internal(raw: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in raw.columns:
        header = canonical_portfolio_header(str(col)) or str(col).strip()
        internal = _DISPLAY_TO_INTERNAL.get(header)
        if internal:
            rename[col] = internal
    return _align_template_columns(raw.rename(columns=rename))


def read_existing_portfolio_positions(path: Path | None = None) -> pd.DataFrame:
    """Load current portfolio sheet rows (internal column names)."""
    raw = read_portfolio_template(path)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    return _portfolio_raw_to_internal(raw)


def _index_existing_positions(existing: pd.DataFrame) -> dict[tuple[str, str], int]:
    index: dict[tuple[str, str], int] = {}
    for idx, row in existing.iterrows():
        platform = _resolve_platform(row.get("Used Platform"), row.get("Position ID"))
        if not platform:
            continue
        for key in _position_id_lookup_keys(platform, row.get("Position ID")):
            index[(platform, key)] = idx
        ticker = row.get("Ticker")
        if not _is_blank(ticker):
            index[(platform, str(ticker).strip().upper())] = idx
    return index


def _match_existing_row_index(
    row: dict[str, Any], index: dict[tuple[str, str], int]
) -> int | None:
    platform = _resolve_platform(row.get("Used Platform"), row.get("Position ID"))
    if not platform:
        return None
    for key in _position_id_lookup_keys(platform, row.get("Position ID")):
        hit = index.get((platform, key))
        if hit is not None:
            return hit
    ticker = row.get("Ticker")
    if not _is_blank(ticker):
        return index.get((platform, str(ticker).strip().upper()))
    return None


def merge_fetched_with_existing(
    fetched: pd.DataFrame, existing: pd.DataFrame
) -> tuple[pd.DataFrame, frozenset[int]]:
    """
    For positions already on the sheet, keep row data and only refresh live fields
    later (Update Date, Price, Exchange Rate). New API positions get a full row.
    """
    if existing.empty:
        return fetched, frozenset()

    existing = _align_template_columns(existing)
    index = _index_existing_positions(existing)
    merged_rows: list[dict[str, Any]] = []
    incremental: set[int] = set()

    for _, api_row in fetched.iterrows():
        api_dict = _normalize_row(api_row.to_dict())
        hit = _match_existing_row_index(api_dict, index)
        if hit is not None:
            merged_rows.append(_normalize_row(existing.loc[hit].to_dict()))
            incremental.add(len(merged_rows) - 1)
        else:
            merged_rows.append(api_dict)

    if not merged_rows:
        return fetched, frozenset()

    out = pd.DataFrame(merged_rows, columns=PORTFOLIO_COLUMNS)
    if incremental:
        logger.info(
            "Portfolio: incremental update for %d existing row(s), "
            "full update for %d new row(s)",
            len(incremental),
            len(out) - len(incremental),
        )
    return out, frozenset(incremental)


def enrich_portfolio_fields(
    df: pd.DataFrame,
    *,
    incremental_row_indices: frozenset[int] | None = None,
) -> pd.DataFrame:
    """Add FX rate, update timestamp; Investment columns use sheet formulas."""
    if df.empty:
        return df

    incremental = incremental_row_indices or frozenset()
    out = _align_template_columns(df).copy()
    from market_source import currency_for_market_source, normalize_market_source

    now = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    currencies: set[str | None] = set()
    historical_pairs: set[tuple[str | None, Any]] = set()
    for idx in out.index:
        if idx in incremental:
            currencies.add(out.at[idx, "Currency"])
            continue
        ticker = out.at[idx, "Ticker"]
        source = normalize_market_source(out.at[idx, "Source"])
        if source:
            out.at[idx, "Source"] = source
        currency = currency_for_market_source(
            source,
            ticker=ticker,
            fallback=out.at[idx, "Currency"],
        )
        out.at[idx, "Currency"] = currency
        currencies.add(currency)
        open_day = parse_open_date_for_fx(out.at[idx, "Open Date"])
        if open_day:
            historical_pairs.add((currency, open_day))
    for idx in incremental:
        currency = out.at[idx, "Currency"]
        if currency:
            currencies.add(currency)
    prefetch_rates_to_eur_on_dates(historical_pairs)
    prefetch_rates_to_eur(currencies)

    for idx in out.index:
        currency = out.at[idx, "Currency"]
        if idx in incremental:
            out.at[idx, "Exchange Rate"] = eur_to_local_rate_on_date(currency, None)
            out.at[idx, "Update Date"] = now
            continue

        open_date = out.at[idx, "Open Date"]
        fx = eur_to_local_rate_on_date(currency, open_date)
        out.at[idx, "Open Exchange Rate"] = fx
        out.at[idx, "Exchange Rate"] = eur_to_local_rate_on_date(currency, None)
        out.at[idx, "Update Date"] = now

        shares = _to_float(out.at[idx, "Shares"])
        price = _to_float(out.at[idx, "Buy Price"])
        fees = _to_float(out.at[idx, "Total Fees"]) or 0.0
        if shares is not None and price is not None:
            investment = shares * price - fees
            out.at[idx, "Investment"] = investment
            if fx:
                out.at[idx, "Investment EUR"] = investment / fx
            else:
                out.at[idx, "Investment EUR"] = None
        else:
            out.at[idx, "Investment"] = None
            out.at[idx, "Investment EUR"] = None

    from portfolio_quotes import fetch_last_prices

    tickers = [str(out.at[idx, "Ticker"]).strip() for idx in out.index]
    last_prices = fetch_last_prices(tickers)
    from market_source import yahoo_price_to_local_pounds

    for idx in out.index:
        sym = str(out.at[idx, "Ticker"]).strip().upper()
        raw_price = last_prices.get(sym)
        out.at[idx, "Price"] = yahoo_price_to_local_pounds(
            raw_price,
            out.at[idx, "Currency"],
            source=out.at[idx, "Source"],
            ticker=sym,
        )

    return out


_PORTFOLIO_FORMATTERS: dict[str, Any] = {
    "Ticker": _fmt_ticker,
    "Full Name": _fmt_text,
    "Source": _fmt_source,
    "Currency": _fmt_currency,
    "Shares": _fmt_shares,
    "Open Date": _fmt_open_date,
    "Buy Price": _fmt_price,
    "Total Fees": _fmt_fees,
    "Investment": _fmt_price,
    "Open Exchange Rate": _fmt_fx_rate,
    "Investment EUR": _fmt_price,
    "Update Date": _fmt_open_date,
    "Price": _fmt_price,
    "Value": _fmt_investment_placeholder,
    "Exchange Rate": _fmt_fx_rate,
    "Value EUR": _fmt_investment_placeholder,
    "Total Return": _fmt_investment_placeholder,
    "Stock Return": _fmt_investment_placeholder,
    "Fee Influence": _fmt_investment_placeholder,
    "Used Platform": _fmt_platform,
    "Position ID": _fmt_position_id,
}


def prepare_portfolio_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Readable headers and typed values for Numbers / Excel export."""
    from numbers_format import coerce_cell_value, infer_column_format

    if df.empty:
        return pd.DataFrame(columns=PORTFOLIO_EXPORT_COLUMNS)
    out = _align_template_columns(df).copy()
    out = out.rename(columns=PORTFOLIO_DISPLAY_NAMES)
    for col in PORTFOLIO_EXPORT_COLUMNS:
        if col not in out.columns:
            continue
        fmt = infer_column_format(col)
        if fmt.kind == "text":
            formatter = _PORTFOLIO_FORMATTERS.get(
                _DISPLAY_TO_INTERNAL.get(col, col),
                _fmt_text,
            )
            out[col] = out[col].map(formatter)
        else:
            out[col] = out[col].map(lambda v, f=fmt: coerce_cell_value(v, f))
    return out[PORTFOLIO_EXPORT_COLUMNS]


def _empty_portfolio_df() -> pd.DataFrame:
    return pd.DataFrame(columns=PORTFOLIO_COLUMNS)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {col: row.get(col) for col in PORTFOLIO_COLUMNS}


def _align_template_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    lower_map = {c.strip().lower(): c for c in df.columns}
    for target in PORTFOLIO_COLUMNS:
        for alias in (target, PORTFOLIO_DISPLAY_NAMES[target]):
            key = alias.lower()
            if key in lower_map:
                rename[lower_map[key]] = target
                break
    out = df.rename(columns=rename)
    for col in PORTFOLIO_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[PORTFOLIO_COLUMNS]


def _portfolio_table_headers(table) -> list[str]:
    return [
        str(table.cell(0, c).value or "").strip()
        for c in range(table.num_cols)
    ]


def _is_portfolio_positions_table(headers: list[str]) -> bool:
    """Distinguish portfolio sheet from summary (both may have Ticker)."""
    header_lower = [h.lower() for h in headers]
    has_symbol = "ticker" in header_lower or "instrument name" in header_lower
    has_portfolio_cols = any(
        token in header_lower
        for token in (
            "position id",
            "used platform",
            "open date [utc]",
            "shares [units]",
        )
    )
    return has_symbol and has_portfolio_cols


def _dataframe_from_numbers_table(table) -> pd.DataFrame | None:
    if table.num_rows < 2:
        return None
    headers = _portfolio_table_headers(table)
    if not _is_portfolio_positions_table(headers):
        return None
    rows = []
    for r in range(1, table.num_rows):
        values = [table.cell(r, c).value for c in range(table.num_cols)]
        if not any(v is not None and str(v).strip() for v in values):
            continue
        rows.append(
            {
                headers[c]: values[c]
                for c in range(len(headers))
                if headers[c]
            }
        )
    return pd.DataFrame(rows) if rows else None


def read_portfolio_template(path: Path | None = None) -> pd.DataFrame | None:
    """
    Load rows from the portfolio sheet in portfolio_summary.numbers (or .xlsx).
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

        target = PORTFOLIO_SHEET_NAME.strip().lower()
        for sheet in doc.sheets:
            if sheet.name.strip().lower() != target:
                continue
            for table in sheet.tables:
                df = _dataframe_from_numbers_table(table)
                if df is not None:
                    return df
            return None

        for sheet in doc.sheets:
            for table in sheet.tables:
                df = _dataframe_from_numbers_table(table)
                if df is not None:
                    logger.warning(
                        "Sheet '%s' not found; read portfolio data from '%s'",
                        PORTFOLIO_SHEET_NAME,
                        sheet.name,
                    )
                    return df
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


def load_preserved_open_dates(path: Path | None = None) -> dict[tuple[str, str], str]:
    """
    Read Open Date from the existing portfolio sheet before it is overwritten.

    Keys: (Used Platform, Position ID) and (Used Platform, Ticker).
    IBKR rows always keep these dates on update when the position is still held.
    """
    raw = read_portfolio_template(path)
    if raw is None or raw.empty:
        return {}

    df = _portfolio_raw_to_internal(raw)

    preserved: dict[tuple[str, str], str] = {}
    for _, row in df.iterrows():
        pos_id = row.get("Position ID")
        platform = _resolve_platform(row.get("Used Platform"), pos_id)
        open_date = row.get("Open Date")
        if not platform or _is_blank(open_date):
            continue
        od = _fmt_open_date(open_date)
        if not od:
            continue
        for key in _position_id_lookup_keys(platform, pos_id):
            preserved[(platform, key)] = od
        ticker = row.get("Ticker")
        if not _is_blank(ticker):
            preserved[(platform, str(ticker).strip().upper())] = od
    if preserved:
        logger.info(
            "Preserved %d open date(s) from existing portfolio sheet", len(preserved)
        )
    return preserved


def _lookup_preserved_open_date(
    row: dict[str, Any], preserved: dict[tuple[str, str], str]
) -> str | None:
    platform = _resolve_platform(row.get("Used Platform"), row.get("Position ID"))
    if not platform:
        return None
    for key in _position_id_lookup_keys(platform, row.get("Position ID")):
        od = preserved.get((platform, key))
        if od:
            return od
    ticker = row.get("Ticker")
    if not _is_blank(ticker):
        return preserved.get((platform, str(ticker).strip().upper()))
    return None


def _apply_preserved_open_dates(
    rows: list[dict[str, Any]], preserved: dict[tuple[str, str], str]
) -> None:
    if not preserved:
        return
    filled = 0
    for row in rows:
        platform = _resolve_platform(row.get("Used Platform"), row.get("Position ID"))
        od = _lookup_preserved_open_date(row, preserved)
        if not od:
            continue
        # IBKR: keep manually entered dates from the sheet (do not replace with API).
        if platform == "IBKR":
            if row.get("Open Date") != od:
                row["Open Date"] = od
                filled += 1
            continue
        if not _is_blank(row.get("Open Date")):
            continue
        row["Open Date"] = od
        filled += 1
    if filled:
        logger.info("Restored open date on %d row(s) from previous sheet", filled)


def fetch_all_positions() -> pd.DataFrame:
    """Fetch positions from enabled brokers; returns normalized DataFrame."""
    from brokers.etoro import fetch_etoro_positions
    from brokers.ibkr import fetch_ibkr_positions

    preserved_dates = load_preserved_open_dates()

    rows: list[dict[str, Any]] = []
    for fetcher, label in (
        (fetch_etoro_positions, "eToro"),
        (fetch_ibkr_positions, "IBKR"),
    ):
        try:
            batch = fetcher()
            for row in batch:
                if not row.get("Used Platform"):
                    row["Used Platform"] = label
            rows.extend(batch)
            logger.info("%s: %d position(s)", label, len(batch))
        except Exception as e:
            logger.warning("%s positions skipped: %s", label, e)

    if not rows:
        return _empty_portfolio_df()

    _apply_preserved_open_dates(rows, preserved_dates)
    normalized = [_normalize_row(r) for r in rows]
    return pd.DataFrame(normalized, columns=PORTFOLIO_COLUMNS)


def build_portfolio_dataframe() -> pd.DataFrame:
    """Live positions from eToro + IBKR, formatted for Numbers / Excel export."""
    existing = read_existing_portfolio_positions()
    fetched = fetch_all_positions()
    merged, incremental = merge_fetched_with_existing(fetched, existing)
    enriched = enrich_portfolio_fields(merged, incremental_row_indices=incremental)
    return prepare_portfolio_for_display(enriched)


def portfolio_summary_path() -> Path:
    return OUTPUT_DIR / PORTFOLIO_SUMMARY_FILENAME
