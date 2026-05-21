"""Build local portfolio summary spreadsheet for long-term analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from config import OUTPUT_DIR, PORTFOLIO_NUMBERS_PATH, PORTFOLIO_OUTPUT
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
    path = OUTPUT_DIR / PORTFOLIO_SUMMARY_FILENAME
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="summary")
        portfolio_df.to_excel(writer, index=False, sheet_name=PORTFOLIO_SHEET_NAME)
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
    summary_df = build_summary_dataframe(results)
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
