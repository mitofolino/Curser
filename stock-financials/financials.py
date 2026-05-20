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


def _safe_df(data) -> pd.DataFrame | None:
    if data is None:
        return None
    if isinstance(data, pd.DataFrame) and not data.empty:
        return data
    return None


def download_statements(ticker: str, out_dir: Path) -> Path | None:
    """Export annual financial statements to one Excel workbook."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stock = yf.Ticker(ticker)
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
