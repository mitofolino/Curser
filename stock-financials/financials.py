from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import DOWNLOAD_QUARTERLY, FMP_API_KEY, SEC_EMAIL
from layout import ETF_XLSX, FINANCIALS_XLSX
from international import (
    fetch_fmp_statement,
    is_non_us_ticker,
    yahoo_symbol_candidates,
)

logger = logging.getLogger(__name__)

STATEMENTS = (
    ("income_statement", "income_stmt"),
    ("balance_sheet", "balance_sheet"),
    ("cash_flow", "cashflow"),
)

QUARTERLY_STATEMENTS = (
    ("income_statement_quarterly", "quarterly_income_stmt"),
    ("balance_sheet_quarterly", "quarterly_balance_sheet"),
    ("cash_flow_quarterly", "quarterly_cashflow"),
)

ETF_INFO_FIELDS = (
    "longName",
    "shortName",
    "category",
    "fundFamily",
    "totalAssets",
    "expenseRatio",
    "yield",
    "ytdReturn",
    "threeYearAverageReturn",
    "fiveYearAverageReturn",
    "beta3Year",
    "fundInceptionDate",
    "legalType",
    "quoteType",
    "currency",
    "exchange",
    "description",
)


def _safe_df(data) -> pd.DataFrame | None:
    if data is None:
        return None
    if isinstance(data, pd.DataFrame) and not data.empty:
        return data
    return None


FUND_QUOTE_TYPES = frozenset({"ETF", "MUTUALFUND"})
NON_FUND_QUOTE_TYPES = frozenset(
    {"EQUITY", "INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE", "OPTION", "WARRANT"}
)


def _export_etf_workbook(ticker: str, info: dict, out_dir: Path) -> Path | None:
    if not info:
        return None
    quote_type = info.get("quoteType")
    if quote_type in NON_FUND_QUOTE_TYPES:
        return None
    if quote_type in FUND_QUOTE_TYPES:
        pass
    elif quote_type is not None:
        return None
    elif not info.get("longName") and not info.get("shortName"):
        return None
    rows = [(k, info.get(k)) for k in ETF_INFO_FIELDS if info.get(k) is not None]
    if not rows:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    name = (info.get("longName") or info.get("shortName") or ticker).strip()
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)[:60]
    path = out_dir / ETF_XLSX
    pd.DataFrame(rows, columns=["field", "value"]).to_excel(path, index=False)
    logger.info("%s: wrote ETF overview %s", ticker, path)
    return path


def _collect_yahoo_sheets(stock: yf.Ticker) -> dict[str, pd.DataFrame]:
    sheets: dict[str, pd.DataFrame] = {}
    for label, attr in STATEMENTS:
        try:
            df = _safe_df(getattr(stock, attr, None))
            if df is not None:
                sheets[label] = df
        except Exception as e:
            logger.warning("Yahoo %s failed: %s", label, e)
    if DOWNLOAD_QUARTERLY:
        for label, attr in QUARTERLY_STATEMENTS:
            try:
                df = _safe_df(getattr(stock, attr, None))
                if df is not None:
                    sheets[label] = df
            except Exception as e:
                logger.warning("Yahoo %s failed: %s", label, e)
    return sheets


def _fill_fmp_quarterly_gaps(
    ticker: str, symbol: str, sheets: dict[str, pd.DataFrame]
) -> None:
    """Use FMP for missing quarterly tabs on non-US names (optional API key)."""
    if not FMP_API_KEY or not is_non_us_ticker(ticker):
        return
    fmp_map = {
        "income_statement_quarterly": "income_statement",
        "balance_sheet_quarterly": "balance_sheet",
        "cash_flow_quarterly": "cash_flow",
    }
    for sheet_name, fmp_type in fmp_map.items():
        if sheet_name in sheets:
            continue
        df = fetch_fmp_statement(
            symbol, fmp_type, api_key=FMP_API_KEY, period="quarter"
        )
        if df is not None:
            sheets[sheet_name] = df
            logger.info("%s: filled %s from FMP (%s)", ticker, sheet_name, symbol)


def _overview_dict(ticker: str, info: dict, yahoo_used: str | None, sheets: dict) -> dict:
    company = (info.get("longName") or info.get("shortName") or ticker).strip()
    has_q = any("quarterly" in name for name in sheets)
    return {
        "company": company,
        "yahoo_symbol": yahoo_used,
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
        "has_annual_statements": bool(
            {"income_statement", "balance_sheet", "cash_flow"} & sheets.keys()
        ),
        "has_quarterly": has_q,
    }


def download_statements(ticker: str, out_dir: Path) -> tuple[Path | None, dict, str]:
    """Export statements to out_dir. Returns (path, overview, instrument_type)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets: dict[str, pd.DataFrame] = {}
    info: dict = {}
    yahoo_used: str | None = None

    for symbol in yahoo_symbol_candidates(ticker):
        stock = yf.Ticker(symbol)
        try:
            candidate_info = stock.info or {}
        except Exception as e:
            logger.warning("%s@%s: could not fetch info: %s", ticker, symbol, e)
            candidate_info = {}
        candidate_sheets = _collect_yahoo_sheets(stock)
        if candidate_sheets:
            sheets = candidate_sheets
            info = candidate_info
            yahoo_used = symbol
            break

    if sheets and yahoo_used:
        _fill_fmp_quarterly_gaps(ticker, yahoo_used, sheets)

    if not sheets:
        etf_path = _export_etf_workbook(ticker, info, out_dir)
        if etf_path:
            meta = _overview_dict(ticker, info, yahoo_used, {})
            meta["quote_type"] = info.get("quoteType")
            return etf_path, meta, "etf"
        logger.error("%s: no financial statement data from Yahoo Finance", ticker)
        return None, {}, "unknown"

    path = out_dir / FINANCIALS_XLSX
    overview = _overview_dict(ticker, info, yahoo_used, sheets)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        rows = [{"field": k, "value": v} for k, v in overview.items()]
        rows.insert(0, {"field": "ticker", "value": ticker})
        pd.DataFrame(rows).to_excel(writer, sheet_name="overview", index=False)
        for name, df in sheets.items():
            export = df.copy()
            export.index.name = "period"
            export.to_excel(writer, sheet_name=name[:31])

    logger.info("%s: wrote %s", ticker, path)
    return path, overview, "stock"


def download_sec_annual_filings(
    ticker: str, out_dir: Path, limit: int
) -> tuple[list[Path], str | None]:
    """Download 10-K; for foreign issuers (e.g. AZN) fall back to 20-F."""
    try:
        from sec_edgar_downloader import Downloader
    except ImportError:
        logger.warning("sec-edgar-downloader not available")
        return [], None

    dl = Downloader("StockFinancials", SEC_EMAIL, str(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    for form in ("10-K", "20-F"):
        try:
            dl.get(form, ticker, limit=limit, download_details=True)
        except Exception as e:
            logger.warning("%s: %s download failed: %s", ticker, form, e)
            continue
        paths = [p for p in out_dir.rglob("*") if p.is_file()]
        if paths:
            if form == "20-F":
                logger.info(
                    "%s: no 10-K found; using 20-F (annual report for foreign issuers)",
                    ticker,
                )
            else:
                logger.info("%s: downloaded %s (%d files)", ticker, form, len(paths))
            return paths, form

    return [], None


def download_10k_filings(ticker: str, out_dir: Path, limit: int) -> list[Path]:
    paths, _ = download_sec_annual_filings(ticker, out_dir, limit)
    return paths
