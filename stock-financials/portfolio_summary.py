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
from international import yahoo_symbol_candidates
from layout import PORTFOLIO_SUMMARY_FILENAME, ticker_dir
from config import PORTFOLIO_SHEET_NAME
from portfolio_positions import _resolve_platform, build_portfolio_dataframe
from ticker_exports import export_dir_keys_for_ticker, resolve_export_dir

logger = logging.getLogger(__name__)

SUMMARY_COLUMNS = [
    "ticker",
    "etoro",
    "ibkr",
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
    "etoro": "eToro",
    "ibkr": "IBKR",
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


def _fmt_true_false(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if _is_blank(value):
        return "FALSE"
    text = str(value).strip().upper()
    if text in ("TRUE", "1", "YES", "Y"):
        return "TRUE"
    return "FALSE"


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
    "etoro": _fmt_true_false,
    "ibkr": _fmt_true_false,
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
        "etoro",
        "ibkr",
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


def _export_folder(ticker: str) -> tuple[str, Path] | None:
    return resolve_export_dir(ticker)


def _latest_income_statement_file(ticker: str) -> Path | None:
    resolved = _export_folder(ticker)
    if resolved is None:
        return None
    _folder_key, folder = resolved
    candidates = sorted(
        folder.glob("*_income_statement*.xlsx"),
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
    resolved = _export_folder(ticker)
    if resolved is None:
        return None, None
    _folder_key, folder = resolved
    annual_files = sorted(
        folder.glob("*_income_statement_annual.xlsx"),
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


def _ticker_keys(ticker: str) -> set[str]:
    return set(export_dir_keys_for_ticker(str(ticker).strip().upper()))


def portfolio_tickers_by_platform(
    portfolio_df: pd.DataFrame,
) -> tuple[set[str], set[str]]:
    """Ticker symbols (uppercase) held on eToro and IBKR in the portfolio sheet."""
    platform_col = "Used Platform" if "Used Platform" in portfolio_df.columns else None
    ticker_col = "Ticker" if "Ticker" in portfolio_df.columns else "ticker"
    if platform_col is None or ticker_col not in portfolio_df.columns:
        return set(), set()

    etoro: set[str] = set()
    ibkr: set[str] = set()
    for _, row in portfolio_df.iterrows():
        symbol = str(row[ticker_col]).strip().upper()
        if not symbol:
            continue
        platform = _resolve_platform(row.get(platform_col), row.get("Position ID"))
        if platform == "eToro":
            etoro.add(symbol)
        elif platform == "IBKR":
            ibkr.add(symbol)
    return etoro, ibkr


def _held_on_platform(summary_ticker: str, platform_tickers: set[str]) -> bool:
    if not platform_tickers:
        return False
    keys = _ticker_keys(summary_ticker)
    for held in platform_tickers:
        if keys & _ticker_keys(held):
            return True
    return False


def build_summary_dataframe(
    results: list[TickerResult],
    *,
    portfolio_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows = [result_to_row(r) for r in results]
    df = pd.DataFrame(rows)
    if portfolio_df is not None and not portfolio_df.empty:
        etoro_held, ibkr_held = portfolio_tickers_by_platform(portfolio_df)
        df["etoro"] = [
            _held_on_platform(str(t), etoro_held) for t in df["ticker"]
        ]
        df["ibkr"] = [
            _held_on_platform(str(t), ibkr_held) for t in df["ticker"]
        ]
    else:
        df["etoro"] = False
        df["ibkr"] = False
    return _apply_eur_columns(df)


def _overview_from_xlsx(path: Path) -> dict[str, Any]:
    df = pd.read_excel(path)
    if "field" not in df.columns or "value" not in df.columns:
        return {}
    out: dict[str, Any] = {}
    for _, row in df.iterrows():
        key = row.get("field")
        if key is None or (isinstance(key, float) and pd.isna(key)):
            continue
        val = row.get("value")
        if isinstance(val, float) and pd.isna(val):
            val = None
        out[str(key)] = val
    if "has_quarterly" in out:
        out["has_quarterly"] = bool(out["has_quarterly"])
    return out


def _ticker_has_exports(dest: Path) -> bool:
    return dest.is_dir() and any(dest.iterdir())


def _sec_form_on_disk(dest: Path) -> str | None:
    names = [
        p.name
        for p in dest.iterdir()
        if p.is_file()
        and "primary" in p.name.lower()
        and ("_10_K_" in p.name or "_20_F_" in p.name)
    ]
    if any("_20_F_" in n for n in names):
        return "20-F"
    if any("_10_K_" in n for n in names):
        return "10-K"
    return None


def _overview_from_yahoo_info(info: dict[str, Any], *, symbol: str, ticker: str) -> dict[str, Any]:
    return {
        "company": (info.get("longName") or info.get("shortName") or ticker).strip(),
        "yahoo_symbol": symbol,
        "country": info.get("country"),
        "currency": info.get("currency"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),
        "profit_margins": info.get("profitMargins"),
        "return_on_equity": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "free_cashflow": info.get("freeCashflow"),
        "website": info.get("website"),
        "has_annual_statements": False,
        "has_quarterly": False,
    }


def _live_overview_from_yahoo(ticker: str) -> tuple[dict[str, Any], str] | None:
    """Fetch company/ETF metrics from Yahoo when no local export folder exists."""
    import yfinance as yf

    for symbol in yahoo_symbol_candidates(ticker):
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as e:
            logger.debug("%s@%s: Yahoo info failed: %s", ticker, symbol, e)
            continue
        if not (
            info.get("longName")
            or info.get("shortName")
            or info.get("marketCap")
        ):
            continue
        quote_type = (info.get("quoteType") or "").upper()
        if quote_type in ("ETF", "MUTUALFUND"):
            instrument = "etf"
        elif quote_type:
            instrument = "stock"
        else:
            instrument = "unknown"
        logger.info("%s: summary from live Yahoo (%s)", ticker, symbol)
        return _overview_from_yahoo_info(info, symbol=symbol, ticker=ticker), instrument
    return None


def load_ticker_result(ticker: str) -> TickerResult:
    """Load overview from disk exports, else live Yahoo; revenue from disk when present."""
    result = TickerResult(ticker=ticker)
    resolved = resolve_export_dir(ticker)

    if resolved is not None:
        folder_key, dest = resolved
        overview_paths = sorted(dest.glob("*_company_overview.xlsx"), reverse=True)
        etf_paths = sorted(dest.glob("*_etf_overview.xlsx"), reverse=True)

        if etf_paths and (
            not overview_paths
            or etf_paths[0].stat().st_mtime >= overview_paths[0].stat().st_mtime
        ):
            result.instrument_type = "etf"
            result.overview = _overview_from_xlsx(etf_paths[0])
        elif overview_paths:
            result.instrument_type = "stock"
            result.overview = _overview_from_xlsx(overview_paths[0])
            result.has_quarterly = bool(result.overview.get("has_quarterly"))

        if result.overview:
            logger.debug("%s: overview from disk (%s)", ticker, folder_key)
        result.sec_form = _sec_form_on_disk(dest)
        result.files_exported = len(list(dest.iterdir()))
        result.ok = bool(result.overview) or _ticker_has_exports(dest)

    if not result.overview:
        live = _live_overview_from_yahoo(ticker)
        if live is not None:
            result.overview, result.instrument_type = live
            result.ok = True
        elif resolved is not None:
            logger.warning(
                "%s: export folder %s has no overview; run: python main.py --tickers %s",
                ticker,
                resolved[0],
                ticker,
            )
        else:
            logger.warning(
                "%s: no export folder under %s; run: python main.py --tickers %s",
                ticker,
                OUTPUT_DIR,
                ticker,
            )

    return result


def distinct_tickers_from_portfolio(portfolio_df: pd.DataFrame) -> list[str]:
    """Unique tickers from the portfolio sheet (display or internal column names)."""
    ticker_col = None
    for name in ("Ticker", "ticker"):
        if name in portfolio_df.columns:
            ticker_col = name
            break
    if ticker_col is None:
        return []

    seen: set[str] = set()
    tickers: list[str] = []
    for value in portfolio_df[ticker_col]:
        if _is_blank(value):
            continue
        symbol = str(value).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append(symbol)
    return sorted(tickers)


def _persist_summary_and_portfolio(
    summary_df: pd.DataFrame, portfolio_df: pd.DataFrame
) -> Path:
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


def save_portfolio_and_summary(
    *,
    portfolio_df: pd.DataFrame | None = None,
) -> tuple[Path, int, int]:
    """
    Refresh portfolio from brokers and summary from distinct portfolio tickers.

    Summary rows use exported overview / statement files under OUTPUT_DIR.
    Returns (path, distinct_ticker_count, summary_rows_ok).
    """
    portfolio_df = (
        portfolio_df
        if portfolio_df is not None
        else build_portfolio_dataframe()
    )
    tickers = distinct_tickers_from_portfolio(portfolio_df)
    logger.info(
        "Summary: %d distinct ticker(s) from %d portfolio row(s)",
        len(tickers),
        len(portfolio_df),
    )
    results = [load_ticker_result(t) for t in tickers]
    summary_df = prepare_summary_for_display(
        build_summary_dataframe(results, portfolio_df=portfolio_df)
    )
    path = _persist_summary_and_portfolio(summary_df, portfolio_df)
    ok = sum(1 for r in results if r.ok)
    return path, len(tickers), ok


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
    """Write summary from explicit results; portfolio still loaded from brokers."""
    portfolio_df = build_portfolio_dataframe()
    summary_df = prepare_summary_for_display(
        build_summary_dataframe(results, portfolio_df=portfolio_df)
    )
    return _persist_summary_and_portfolio(summary_df, portfolio_df)
