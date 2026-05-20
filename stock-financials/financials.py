from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import SEC_EMAIL

logger = logging.getLogger(__name__)

STATEMENTS = (
    ("income_statement", "income_stmt"),
    ("balance_sheet", "balance_sheet"),
    ("cash_flow", "cashflow"),
)

# Sheet ticker -> Yahoo symbol (ETFs / UCITS often need exchange suffix)
YAHOO_ALIASES: dict[str, str] = {
    "SWDA": "SWDA.L",
    "IUSA": "IUSA.L",
}

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


def _yahoo_symbol(ticker: str) -> str:
    return YAHOO_ALIASES.get(ticker.upper(), ticker)


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
    path = out_dir / f"{ticker}_{safe_name}_etf_overview.xlsx"
    pd.DataFrame(rows, columns=["field", "value"]).to_excel(path, index=False)
    logger.info("%s: wrote ETF overview %s", ticker, path)
    return path


def download_statements(ticker: str, out_dir: Path) -> Path | None:
    """Export annual financial statements to one Excel workbook."""
    out_dir.mkdir(parents=True, exist_ok=True)
    yahoo = _yahoo_symbol(ticker)
    stock = yf.Ticker(yahoo)
    info = {}
    try:
        info = stock.info or {}
    except Exception as e:
        logger.warning("%s: could not fetch info: %s", ticker, e)

    sheets: dict[str, pd.DataFrame] = {}
    for label, attr in STATEMENTS:
        try:
            df = _safe_df(getattr(stock, attr, None))
            if df is not None:
                sheets[label] = df
        except Exception as e:
            logger.warning("%s: %s failed: %s", ticker, label, e)

    if not sheets:
        etf_path = _export_etf_workbook(ticker, info, out_dir)
        if etf_path:
            return etf_path
        logger.error("%s: no financial statement data from Yahoo Finance", ticker)
        return None

    company = (info.get("longName") or info.get("shortName") or ticker).strip()
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in company)[:60]
    path = out_dir / f"{ticker}_{safe_name}_financials.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        meta = pd.DataFrame(
            {
                "field": [
                    "ticker",
                    "company",
                    "sector",
                    "industry",
                    "market_cap",
                    "trailing_pe",
                    "forward_pe",
                    "dividend_yield",
                    "profit_margins",
                    "return_on_equity",
                    "debt_to_equity",
                    "free_cashflow",
                    "website",
                ],
                "value": [
                    ticker,
                    company,
                    info.get("sector"),
                    info.get("industry"),
                    info.get("marketCap"),
                    info.get("trailingPE"),
                    info.get("forwardPE"),
                    info.get("dividendYield"),
                    info.get("profitMargins"),
                    info.get("returnOnEquity"),
                    info.get("debtToEquity"),
                    info.get("freeCashflow"),
                    info.get("website"),
                ],
            }
        )
        meta.to_excel(writer, sheet_name="overview", index=False)
        for name, df in sheets.items():
            export = df.copy()
            export.index.name = "period"
            export.to_excel(writer, sheet_name=name[:31])

    logger.info("%s: wrote %s", ticker, path)
    return path


def download_10k_filings(ticker: str, out_dir: Path, limit: int) -> list[Path]:
    """Download recent 10-K annual reports from SEC EDGAR."""
    try:
        from sec_edgar_downloader import Downloader
    except ImportError:
        logger.warning("sec-edgar-downloader not available")
        return []

    dl = Downloader("StockFinancials", SEC_EMAIL, str(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        dl.get("10-K", ticker, limit=limit, download_details=True)
    except Exception as e:
        logger.warning("%s: 10-K download failed: %s", ticker, e)
        return []

    return list(out_dir.rglob("*"))
