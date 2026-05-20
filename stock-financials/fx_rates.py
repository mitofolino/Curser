"""Fetch recent FX rates and convert monetary values to EUR."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.app/latest"
_CACHE: dict[str, float] = {"EUR": 1.0}

# Yahoo / vendor quirks
_CURRENCY_ALIASES = {
    "GBP": "GBP",
    "GBX": "GBP",  # pence quoted; amounts from Yahoo are usually in GBP not pence
    "GBp": "GBP",
}


def normalize_currency(code: Any) -> str | None:
    if code is None or (isinstance(code, float) and code != code):
        return None
    text = str(code).strip().upper()
    if not text:
        return None
    return _CURRENCY_ALIASES.get(text, text)


def rate_to_eur(currency: str | None) -> float | None:
    """Return multiplier: amount_in_currency * rate = amount_in_EUR."""
    code = normalize_currency(currency)
    if code is None:
        return None
    if code == "EUR":
        return 1.0
    if code in _CACHE:
        return _CACHE[code]
    try:
        res = requests.get(
            FRANKFURTER_URL,
            params={"from": code, "to": "EUR"},
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        rate = float(data["rates"]["EUR"])
        _CACHE[code] = rate
        logger.debug("FX %s->EUR: %s (date %s)", code, rate, data.get("date"))
        return rate
    except Exception as e:
        logger.warning("FX rate %s->EUR failed: %s", code, e)
        return None


def prefetch_rates_to_eur(currencies: set[str | None]) -> None:
    for c in currencies:
        if c:
            rate_to_eur(c)


def to_eur(amount: Any, currency: str | None) -> float | None:
    if amount is None or amount == "":
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    rate = rate_to_eur(currency)
    if rate is None:
        return None
    return round(value * rate, 2)
