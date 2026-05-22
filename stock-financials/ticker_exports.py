"""Map portfolio / sheet tickers to on-disk export folders under OUTPUT_DIR."""

from __future__ import annotations

import logging
from pathlib import Path

from config import OUTPUT_DIR
from international import YAHOO_ALIASES, strip_broker_listing_suffix, yahoo_symbol_candidates
from layout import ticker_dir

logger = logging.getLogger(__name__)


def export_dir_keys_for_ticker(ticker: str) -> list[str]:
    """
    Folder names under OUTPUT_DIR that may hold downloads for this symbol.

    Portfolio tickers (e.g. IUSA.L, MDT.US) often differ from the folder used
    when ``main.py`` ran (e.g. IUSA, MDT).
    """
    upper = ticker.upper().strip()
    keys: list[str] = []

    def add(key: str | None) -> None:
        if key and key not in keys:
            keys.append(key)

    add(upper)
    bare = strip_broker_listing_suffix(upper)
    if bare:
        add(bare)
    for sym in yahoo_symbol_candidates(upper):
        add(sym)
    for alias_key, alias_val in YAHOO_ALIASES.items():
        if alias_val.upper() == upper:
            add(alias_key)
        if alias_key.upper() == upper:
            add(alias_val)
    return keys


def resolve_export_dir(ticker: str) -> tuple[str, Path] | None:
    """First existing non-empty export directory for *ticker*, or None."""
    for key in export_dir_keys_for_ticker(ticker):
        path = ticker_dir(OUTPUT_DIR, key)
        if path.is_dir() and any(path.iterdir()):
            return key, path

    upper = ticker.upper().strip()
    if OUTPUT_DIR.is_dir():
        for path in OUTPUT_DIR.iterdir():
            if path.is_dir() and path.name.upper() == upper and any(path.iterdir()):
                return path.name, path
    return None
