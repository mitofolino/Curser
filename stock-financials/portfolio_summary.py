"""Build and upload root portfolio summary for long-term analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from config import DRIVE_FOLDER_ID, LOCAL_OUTPUT_DIR
from drive_upload import upload_portfolio_summary_sheet
from fx_rates import normalize_currency, prefetch_rates_to_eur, rate_to_eur, to_eur
from layout import FINANCIALS_XLSX, SUMMARY_SHEET_NAME, statements_dir

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
    statement_file: str | None = None


def _pct(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        v = float(value)
        return round(v * 100, 2) if abs(v) <= 1.5 else round(v, 2)
    except (TypeError, ValueError):
        return value


def _revenue_metrics(ticker: str, statements_path: Path) -> tuple[Any, Any]:
    """Latest revenue and approximate 5y growth from annual income statement."""
    try:
        df = pd.read_excel(statements_path, sheet_name="income_statement", index_col=0)
    except Exception:
        return None, None
    rev_row = None
    for name in ("Total Revenue", "Revenue", "Operating Revenue"):
        if name in df.index:
            rev_row = df.loc[name]
            break
    if rev_row is None or rev_row.empty:
        return None, None
    series = pd.to_numeric(rev_row, errors="coerce").dropna()
    if series.empty:
        return None, None
    latest = float(series.iloc[0])
    if len(series) >= 5:
        oldest = float(series.iloc[4])
        if oldest > 0:
            growth = (latest / oldest) ** (1 / 5) - 1
            return latest, round(growth * 100, 2)
    return latest, None


def result_to_row(result: TickerResult) -> dict[str, Any]:
    ov = result.overview
    rev_latest, rev_growth = None, None
    if result.statement_file == FINANCIALS_XLSX:
        path = statements_dir(LOCAL_OUTPUT_DIR, result.ticker) / FINANCIALS_XLSX
        if path.exists():
            rev_latest, rev_growth = _revenue_metrics(result.ticker, path)

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


def save_and_upload_summary(
    results: list[TickerResult],
    *,
    upload: bool,
) -> Path:
    df = build_summary_dataframe(results)
    LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    local_xlsx = LOCAL_OUTPUT_DIR / "portfolio_summary.xlsx"
    df.to_excel(local_xlsx, index=False, sheet_name="summary")
    logger.info("Wrote local summary: %s", local_xlsx)

    if upload:
        url = upload_portfolio_summary_sheet(
            df, DRIVE_FOLDER_ID, title=SUMMARY_SHEET_NAME
        )
        logger.info("Portfolio summary Google Sheet: %s", url)
    return local_xlsx
