from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import DOWNLOAD_QUARTERLY, FMP_API_KEY, SEC_EMAIL
from config import STATEMENT_YEARS
from layout import (
    etf_overview_filename,
    overview_filename,
    period_within_statement_window,
    statement_filename,
)
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
    path = out_dir / etf_overview_filename(ticker)
    pd.DataFrame(rows, columns=["field", "value"]).to_excel(path, index=False)
    logger.info("%s: wrote ETF overview %s", ticker, path)
    return path


def _export_statement_files(
    ticker: str, sheets: dict[str, pd.DataFrame], out_dir: Path
) -> list[Path]:
    """One file per period per statement type (last STATEMENT_YEARS years only)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for statement_type, df in sheets.items():
        periods = [p for p in df.columns if period_within_statement_window(p)]
        if not periods:
            logger.info(
                "%s: no %s periods within last %d years",
                ticker,
                statement_type,
                STATEMENT_YEARS,
            )
            continue
        for period in periods:
            col_df = df[[period]].copy()
            col_df.index.name = "line_item"
            fname = statement_filename(ticker, period, statement_type)
            path = out_dir / fname
            col_df.to_excel(path)
            written.append(path)
            logger.info("%s: wrote %s", ticker, fname)
    return written


def _export_overview_file(ticker: str, overview: dict) -> Path:
    out_dir = overview.get("_out_dir")
    if out_dir is None:
        raise ValueError("overview missing _out_dir")
    path = Path(out_dir) / overview_filename(ticker)
    rows = [{"field": k, "value": v} for k, v in overview.items() if not k.startswith("_")]
    rows.insert(0, {"field": "ticker", "value": ticker})
    pd.DataFrame(rows).to_excel(path, index=False)
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
            symbol,
            fmp_type,
            api_key=FMP_API_KEY,
            period="quarter",
            limit=STATEMENT_YEARS * 4,
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


def download_statements(
    ticker: str, out_dir: Path
) -> tuple[list[Path], dict, str]:
    """Export files to ticker folder. Returns (paths, overview, instrument_type)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets: dict[str, pd.DataFrame] = {}
    info: dict = {}
    best_info: dict = {}
    yahoo_used: str | None = None

    for symbol in yahoo_symbol_candidates(ticker):
        stock = yf.Ticker(symbol)
        try:
            candidate_info = stock.info or {}
        except Exception as e:
            logger.warning("%s@%s: could not fetch info: %s", ticker, symbol, e)
            candidate_info = {}
        if candidate_info:
            if not best_info or candidate_info.get("quoteType") in FUND_QUOTE_TYPES:
                best_info = candidate_info
        candidate_sheets = _collect_yahoo_sheets(stock)
        if candidate_sheets:
            sheets = candidate_sheets
            info = candidate_info
            yahoo_used = symbol
            break

    if not info and best_info:
        info = best_info

    if sheets and yahoo_used:
        _fill_fmp_quarterly_gaps(ticker, yahoo_used, sheets)

    if not sheets:
        etf_path = _export_etf_workbook(ticker, info, out_dir)
        if etf_path:
            meta = _overview_dict(ticker, info, yahoo_used, {})
            meta["quote_type"] = info.get("quoteType")
            return [etf_path], meta, "etf"
        logger.error("%s: no financial statement data from Yahoo Finance", ticker)
        return [], {}, "unknown"

    overview = _overview_dict(ticker, info, yahoo_used, sheets)
    overview["_out_dir"] = str(out_dir)
    paths = _export_statement_files(ticker, sheets, out_dir)
    paths.append(_export_overview_file(ticker, overview))
    return paths, overview, "stock"


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
