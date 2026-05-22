"""Symbol resolution and optional fallback data for non-US listings."""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Tickers without an exchange suffix that should use a local listing on Yahoo
YAHOO_ALIASES: dict[str, str] = {
    "SWDA": "SWDA.L",
    "IUSA": "IUSA.L",
}

NON_US_SUFFIX = re.compile(
    r"\.(HK|DE|L|PA|TO|AX|SW|T|TW|KS|SI|MU|AS|BR|MX|SS|SZ|KQ|VI|BC|SN)$",
    re.IGNORECASE,
)

# eToro / broker listing tags — not valid Yahoo symbols (use bare ticker instead)
_BROKER_LISTING_SUFFIX = re.compile(r"\.(US|UK|LON)$", re.IGNORECASE)

FMP_STATEMENTS = {
    "income_statement": "income-statement",
    "balance_sheet": "balance-sheet-statement",
    "cash_flow": "cash-flow-statement",
}


def is_non_us_ticker(ticker: str) -> bool:
    return bool(NON_US_SUFFIX.search(ticker))


def strip_broker_listing_suffix(ticker: str) -> str | None:
    """e.g. T.US → T, MDT.US → MDT (Yahoo uses bare US symbols)."""
    upper = ticker.upper().strip()
    bare = _BROKER_LISTING_SUFFIX.sub("", upper)
    return bare if bare and bare != upper else None


def yahoo_symbol_candidates(ticker: str) -> list[str]:
    """Order of Yahoo symbols to try (sheet ticker first, then mapped listing)."""
    upper = ticker.upper().strip()
    candidates: list[str] = []

    def add(sym: str | None) -> None:
        if sym and sym not in candidates:
            candidates.append(sym)

    bare = strip_broker_listing_suffix(upper)
    if bare:
        add(bare)
    add(upper)

    alias = YAHOO_ALIASES.get(upper) or (bare and YAHOO_ALIASES.get(bare))
    if alias:
        add(alias)

    if is_non_us_ticker(upper):
        return candidates

    # Bare tickers: also try common home listings for known names
    extra = {
        "AZN": "AZN.L",
        "RBOT": "RBOT.L",
        "TSM": "TSM",
        "SAP": "SAP.DE",
        "NVO": "NVO",
    }
    for key in (upper, bare):
        if not key:
            continue
        alt = extra.get(key)
        if alt:
            add(alt)
    return candidates


def fetch_fmp_statement(
    symbol: str,
    statement: str,
    *,
    api_key: str,
    period: str = "quarter",
    limit: int = 24,
) -> pd.DataFrame | None:
    """Fetch annual or quarterly statements from Financial Modeling Prep."""
    endpoint = FMP_STATEMENTS.get(statement)
    if not endpoint:
        return None
    url = f"https://financialmodelingprep.com/api/v3/{endpoint}/{symbol}"
    try:
        res = requests.get(
            url,
            params={"period": period, "limit": limit, "apikey": api_key},
            timeout=30,
        )
        res.raise_for_status()
        data: list[dict[str, Any]] = res.json()
    except Exception as e:
        logger.warning("FMP %s %s failed: %s", symbol, statement, e)
        return None
    if not data:
        return None
    df = pd.DataFrame(data)
    if "date" not in df.columns:
        return None
    df = df.set_index("date").sort_index(axis=0)
    # Match Yahoo layout: line items as rows, periods as columns
    return df.T
