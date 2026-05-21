"""Live market prices for portfolio tickers (Yahoo Finance)."""

from __future__ import annotations

import logging

from international import yahoo_symbol_candidates

logger = logging.getLogger(__name__)


def _last_close(symbol: str) -> float | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        hist = yf.Ticker(symbol).history(period="5d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].dropna().iloc[-1])
    except Exception:
        return None


def fetch_last_prices(tickers: list[str]) -> dict[str, float | None]:
    """Map sheet ticker → last close in local listing currency."""
    out: dict[str, float | None] = {}
    for raw in tickers:
        key = str(raw).strip().upper()
        if not key or key in out:
            continue
        tried: list[str] = []
        price = None
        for symbol in yahoo_symbol_candidates(key):
            tried.append(symbol)
            price = _last_close(symbol)
            if price is not None:
                if symbol != key:
                    logger.debug("Price for %s via Yahoo symbol %s", key, symbol)
                break
        if price is None and tried:
            logger.warning(
                "No Yahoo price for %s (tried: %s)",
                key,
                ", ".join(tried),
            )
        out[key] = price
    return out
