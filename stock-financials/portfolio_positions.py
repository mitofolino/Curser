"""Merge live positions from eToro and IBKR into the portfolio sheet."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config import OUTPUT_DIR, PORTFOLIO_NUMBERS_PATH, PORTFOLIO_SHEET_NAME
from fx_rates import (
    eur_to_local_rate_on_date,
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


def _fmt_open_date(value: Any) -> str:
    return _fmt_text(value)


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


def _to_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enrich_portfolio_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add FX rate, update timestamp; Investment columns use sheet formulas."""
    if df.empty:
        return df

    out = _align_template_columns(df).copy()
    from market_source import currency_for_market_source, normalize_market_source

    now = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    for idx in out.index:
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

    pairs = {
        (out.at[idx, "Currency"], str(out.at[idx, "Open Date"] or "")[:10])
        for idx in out.index
        if out.at[idx, "Currency"]
    }
    prefetch_rates_to_eur_on_dates(pairs)
    prefetch_rates_to_eur({out.at[idx, "Currency"] for idx in out.index})

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
    return pd.DataFrame(columns=PORTFOLIO_EXPORT_COLUMNS)


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
                header_lower = [h.lower() for h in headers]
                if "ticker" not in header_lower and "instrument name" not in header_lower:
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
    """Live positions from eToro + IBKR, formatted for Numbers / Excel export."""
    return prepare_portfolio_for_display(enrich_portfolio_fields(fetch_all_positions()))


def portfolio_summary_path() -> Path:
    return OUTPUT_DIR / PORTFOLIO_SUMMARY_FILENAME
