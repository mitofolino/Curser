"""Build local portfolio summary spreadsheet for long-term analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from config import (
    OUTPUT_DIR,
    PORTFOLIO_DATA_START_ROW,
    PORTFOLIO_NUMBERS_PATH,
    PORTFOLIO_OUTPUT,
)
from fx_rates import normalize_currency, prefetch_rates_to_eur, rate_to_eur, to_eur
from layout import PORTFOLIO_SUMMARY_FILENAME, ticker_dir
from config import PORTFOLIO_SHEET_NAME
from portfolio_positions import build_portfolio_dataframe

logger = logging.getLogger(__name__)

SUMMARY_COLUMNS = [
    "ticker",
    "company",
    "country",
    "currency",
    "sector",
    "industry",
    "yahoo_symbol",
    "instrument_type",
    "market_cap",
    "market_cap_eur",
    "trailing_pe",
    "forward_pe",
    "dividend_yield",
    "profit_margins",
    "return_on_equity",
    "debt_to_equity",
    "free_cashflow",
    "free_cashflow_eur",
    "revenue_latest",
    "revenue_latest_eur",
    "fx_rate_to_eur",
    "revenue_growth_5y",
    "has_annual_statements",
    "has_quarterly_statements",
    "sec_filing",
    "status",
    "website",
]

# Human-readable headers for Numbers / Excel (units in square brackets)
SUMMARY_DISPLAY_NAMES: dict[str, str] = {
    "ticker": "Ticker",
    "company": "Company",
    "country": "Country",
    "currency": "Currency",
    "sector": "Sector",
    "industry": "Industry",
    "yahoo_symbol": "Yahoo Symbol",
    "instrument_type": "Instrument Type",
    "market_cap": "Market Cap [local]",
    "market_cap_eur": "Market Cap [EUR]",
    "trailing_pe": "P/E Ratio (TTM)",
    "forward_pe": "Forward P/E",
    "dividend_yield": "Dividend Yield [%]",
    "profit_margins": "Profit Margin [%]",
    "return_on_equity": "Return on Equity [%]",
    "debt_to_equity": "Debt to Equity [ratio]",
    "free_cashflow": "Free Cash Flow [local]",
    "free_cashflow_eur": "Free Cash Flow [EUR]",
    "revenue_latest": "Revenue Latest [local]",
    "revenue_latest_eur": "Revenue Latest [EUR]",
    "fx_rate_to_eur": "FX Rate to EUR",
    "revenue_growth_5y": "Revenue Growth 5Y [%]",
    "has_annual_statements": "Annual Statements",
    "has_quarterly_statements": "Quarterly Statements",
    "sec_filing": "SEC Filing",
    "status": "Status",
    "website": "Website",
}


@dataclass
class TickerResult:
    ticker: str
    ok: bool = False
    instrument_type: str = ""  # stock | etf | unknown
    overview: dict[str, Any] = field(default_factory=dict)
    has_quarterly: bool = False
    sec_form: str | None = None
    files_exported: int = 0


def _pct(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        v = float(value)
        return round(v * 100, 2) if abs(v) <= 1.5 else round(v, 2)
    except (TypeError, ValueError):
        return value


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _fmt_compact_amount(value: Any) -> str:
    """Large monetary values: 1.23 B, 456.7 M, 12.3 K."""
    if _is_blank(value):
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if v < 0 else ""
    n = abs(v)
    for threshold, suffix in (
        (1e12, "T"),
        (1e9, "B"),
        (1e6, "M"),
        (1e3, "K"),
    ):
        if n >= threshold:
            return f"{sign}{n / threshold:.2f} {suffix}"
    return f"{sign}{n:,.0f}"


def _fmt_decimal(value: Any, places: int = 2) -> str:
    if _is_blank(value):
        return ""
    try:
        return f"{float(value):.{places}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_percent(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_fx_rate(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_yes_no(value: Any) -> str:
    if _is_blank(value):
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return "Yes"
    if text in ("0", "false", "no", "n"):
        return "No"
    return str(value)


def _fmt_text(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _fmt_instrument_type(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip().replace("_", " ").title()


def _fmt_status(value: Any) -> str:
    text = _fmt_text(value)
    if not text:
        return ""
    return text.upper() if text.lower() == "ok" else text.title()


_SUMMARY_FORMATTERS: dict[str, Any] = {
    "ticker": _fmt_text,
    "company": _fmt_text,
    "country": _fmt_text,
    "currency": _fmt_text,
    "sector": _fmt_text,
    "industry": _fmt_text,
    "yahoo_symbol": _fmt_text,
    "instrument_type": _fmt_instrument_type,
    "market_cap": _fmt_compact_amount,
    "market_cap_eur": _fmt_compact_amount,
    "trailing_pe": lambda v: _fmt_decimal(v, 2),
    "forward_pe": lambda v: _fmt_decimal(v, 2),
    "dividend_yield": _fmt_percent,
    "profit_margins": _fmt_percent,
    "return_on_equity": _fmt_percent,
    "debt_to_equity": lambda v: _fmt_decimal(v, 2),
    "free_cashflow": _fmt_compact_amount,
    "free_cashflow_eur": _fmt_compact_amount,
    "revenue_latest": _fmt_compact_amount,
    "revenue_latest_eur": _fmt_compact_amount,
    "fx_rate_to_eur": _fmt_fx_rate,
    "revenue_growth_5y": _fmt_percent,
    "has_annual_statements": _fmt_yes_no,
    "has_quarterly_statements": _fmt_yes_no,
    "sec_filing": _fmt_text,
    "status": _fmt_status,
    "website": _fmt_text,
}


def prepare_summary_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Readable headers and typed values for Numbers / Excel export."""
    from numbers_format import coerce_cell_value, infer_column_format

    out = df.copy()
    out = out.rename(columns=SUMMARY_DISPLAY_NAMES)
    text_cols = {
        "ticker",
        "company",
        "country",
        "currency",
        "sector",
        "industry",
        "yahoo_symbol",
        "instrument_type",
        "has_annual_statements",
        "has_quarterly_statements",
        "sec_filing",
        "status",
        "website",
    }
    for col in SUMMARY_COLUMNS:
        display = SUMMARY_DISPLAY_NAMES[col]
        if display not in out.columns:
            continue
        if col in text_cols:
            formatter = _SUMMARY_FORMATTERS.get(col, _fmt_text)
            out[display] = out[display].map(formatter)
        else:
            fmt = infer_column_format(display)
            out[display] = out[display].map(lambda v, f=fmt: coerce_cell_value(v, f))
    return out[[SUMMARY_DISPLAY_NAMES[c] for c in SUMMARY_COLUMNS]]


def _latest_income_statement_file(ticker: str) -> Path | None:
    folder = ticker_dir(OUTPUT_DIR, ticker)
    if not folder.exists():
        return None
    candidates = sorted(
        folder.glob(f"{ticker}_*_income_statement*.xlsx"),
        reverse=True,
    )
    annual = [p for p in candidates if "annual" in p.name.lower()]
    return (annual or candidates)[0] if (annual or candidates) else None


def _revenue_from_file(path: Path) -> float | None:
    try:
        df = pd.read_excel(path, index_col=0)
    except Exception:
        return None
    for name in ("Total Revenue", "Revenue", "Operating Revenue"):
        if name in df.index:
            row = df.loc[name]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[:, 0]
            val = pd.to_numeric(row, errors="coerce").dropna()
            if not val.empty:
                return float(val.iloc[0])
    return None


def _revenue_metrics(ticker: str) -> tuple[Any, Any]:
    """Latest revenue and approximate 5y growth from annual income statement files."""
    folder = ticker_dir(OUTPUT_DIR, ticker)
    annual_files = sorted(
        folder.glob(f"{ticker}_*_income_statement_annual.xlsx"),
        reverse=True,
    )
    if not annual_files:
        path = _latest_income_statement_file(ticker)
        if path:
            latest = _revenue_from_file(path)
            return latest, None
        return None, None
    revenues = [_revenue_from_file(p) for p in annual_files]
    revenues = [r for r in revenues if r is not None]
    if not revenues:
        return None, None
    latest = revenues[0]
    if len(revenues) >= 5 and revenues[-1] > 0:
        growth = (latest / revenues[-1]) ** (1 / 5) - 1
        return latest, round(growth * 100, 2)
    return latest, None


def result_to_row(result: TickerResult) -> dict[str, Any]:
    ov = result.overview
    rev_latest, rev_growth = _revenue_metrics(result.ticker)

    return {
        "ticker": result.ticker,
        "company": ov.get("company"),
        "country": ov.get("country"),
        "currency": ov.get("currency"),
        "sector": ov.get("sector"),
        "industry": ov.get("industry"),
        "yahoo_symbol": ov.get("yahoo_symbol"),
        "instrument_type": result.instrument_type,
        "market_cap": ov.get("market_cap"),
        "trailing_pe": ov.get("trailing_pe"),
        "forward_pe": ov.get("forward_pe"),
        "dividend_yield": _pct(ov.get("dividend_yield")),
        "profit_margins": _pct(ov.get("profit_margins")),
        "return_on_equity": _pct(ov.get("return_on_equity")),
        "debt_to_equity": ov.get("debt_to_equity"),
        "free_cashflow": ov.get("free_cashflow"),
        "revenue_latest": rev_latest,
        "revenue_growth_5y": rev_growth,
        "has_annual_statements": ov.get("has_annual_statements"),
        "has_quarterly_statements": result.has_quarterly,
        "sec_filing": result.sec_form or "",
        "status": "ok" if result.ok else "failed",
        "website": ov.get("website"),
    }


def _apply_eur_columns(df: pd.DataFrame) -> pd.DataFrame:
    currencies = {normalize_currency(c) for c in df["currency"].tolist()}
    prefetch_rates_to_eur({c for c in currencies if c})

    df = df.copy()
    df["fx_rate_to_eur"] = df["currency"].map(rate_to_eur)
    df["market_cap_eur"] = [
        to_eur(m, c) for m, c in zip(df["market_cap"], df["currency"])
    ]
    df["free_cashflow_eur"] = [
        to_eur(f, c) for f, c in zip(df["free_cashflow"], df["currency"])
    ]
    df["revenue_latest_eur"] = [
        to_eur(r, c) for r, c in zip(df["revenue_latest"], df["currency"])
    ]
    return df[SUMMARY_COLUMNS]


def build_summary_dataframe(results: list[TickerResult]) -> pd.DataFrame:
    rows = [result_to_row(r) for r in results]
    df = pd.DataFrame(rows)
    return _apply_eur_columns(df)


def _save_summary_xlsx(
    summary_df: pd.DataFrame, portfolio_df: pd.DataFrame
) -> Path:
    from excel_format import apply_sheet_formats
    from portfolio_formulas import apply_portfolio_formulas_openpyxl

    path = OUTPUT_DIR / PORTFOLIO_SUMMARY_FILENAME
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="summary")
        portfolio_df.to_excel(writer, index=False, sheet_name=PORTFOLIO_SHEET_NAME)
        apply_sheet_formats(writer.sheets["summary"], data_start_row=2)
        if not portfolio_df.empty:
            apply_portfolio_formulas_openpyxl(
                writer.sheets[PORTFOLIO_SHEET_NAME], len(portfolio_df)
            )
        apply_sheet_formats(
            writer.sheets[PORTFOLIO_SHEET_NAME],
            data_start_row=PORTFOLIO_DATA_START_ROW,
        )
    logger.info(
        "Wrote %s (summary: %d rows, %s: %d rows)",
        path,
        len(summary_df),
        PORTFOLIO_SHEET_NAME,
        len(portfolio_df),
    )
    return path


def _save_summary_numbers(
    summary_df: pd.DataFrame, portfolio_df: pd.DataFrame
) -> Path:
    from numbers_export import save_to_numbers

    path = save_to_numbers(
        PORTFOLIO_NUMBERS_PATH,
        summary_df=summary_df,
        portfolio_df=portfolio_df,
        summary_sheet="summary",
        portfolio_sheet=PORTFOLIO_SHEET_NAME,
    )
    logger.info(
        "Wrote %s (summary: %d rows, %s: %d rows)",
        path,
        len(summary_df),
        PORTFOLIO_SHEET_NAME,
        len(portfolio_df),
    )
    return path


def save_summary(results: list[TickerResult]) -> Path:
    summary_df = prepare_summary_for_display(build_summary_dataframe(results))
    portfolio_df = build_portfolio_dataframe()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    mode = PORTFOLIO_OUTPUT
    last_path = PORTFOLIO_NUMBERS_PATH

    if mode in ("xlsx", "both"):
        last_path = _save_summary_xlsx(summary_df, portfolio_df)
    if mode in ("numbers", "both"):
        last_path = _save_summary_numbers(summary_df, portfolio_df)
    if mode not in ("xlsx", "numbers", "both"):
        logger.warning("Unknown PORTFOLIO_OUTPUT=%s; using numbers", mode)
        last_path = _save_summary_numbers(summary_df, portfolio_df)

    return last_path
