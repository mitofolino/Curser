"""Fetch recent FX rates and convert monetary values to EUR."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.app/latest"
_CACHE: dict[str, float] = {"EUR": 1.0}
_HISTORICAL_CACHE: dict[tuple[str, str], float] = {}

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


def _fetch_rate_to_eur(code: str, *, on_date: str | None = None) -> float | None:
    if code == "EUR":
        return 1.0
    if on_date:
        cache_key = (code, on_date)
        if cache_key in _HISTORICAL_CACHE:
            return _HISTORICAL_CACHE[cache_key]
        url = f"https://api.frankfurter.app/{on_date}"
    else:
        if code in _CACHE:
            return _CACHE[code]
        url = FRANKFURTER_URL

    try:
        res = requests.get(url, params={"from": code, "to": "EUR"}, timeout=15)
        res.raise_for_status()
        data = res.json()
        rate = float(data["rates"]["EUR"])
        if on_date:
            _HISTORICAL_CACHE[(code, on_date)] = rate
        else:
            _CACHE[code] = rate
        logger.debug(
            "FX %s->EUR: %s (date %s)",
            code,
            rate,
            data.get("date") or on_date,
        )
        return rate
    except Exception as e:
        logger.warning("FX rate %s->EUR failed (%s): %s", code, on_date or "latest", e)
        return None


def rate_to_eur_on_date(currency: str | None, open_date: Any) -> float | None:
    """Multiplier: amount in *currency* × rate = amount in EUR (for *open_date*, UTC date)."""
    code = normalize_currency(currency)
    if code is None:
        return None
    if code == "EUR":
        return 1.0
    if open_date is None or open_date == "":
        return rate_to_eur(code)
    text = str(open_date).strip()
    on_date = text[:10] if len(text) >= 10 else text
    rate = _fetch_rate_to_eur(code, on_date=on_date)
    return rate if rate is not None else rate_to_eur(code)


def eur_to_local_rate_on_date(currency: str | None, open_date: Any) -> float | None:
    """How many units of *local* currency per 1 EUR (for open-date FX)."""
    rate = rate_to_eur_on_date(currency, open_date)
    if rate is None or rate == 0:
        return None
    if normalize_currency(currency) == "EUR":
        return 1.0
    return 1.0 / rate


def prefetch_rates_to_eur_on_dates(pairs: set[tuple[str | None, str]]) -> None:
    """Warm cache for (currency, YYYY-MM-DD) pairs."""
    for currency, open_date in pairs:
        rate_to_eur_on_date(currency, open_date)


def rate_to_eur(currency: str | None) -> float | None:
    """Return multiplier: amount_in_currency * rate = amount_in_EUR."""
    code = normalize_currency(currency)
    if code is None:
        return None
    return _fetch_rate_to_eur(code)


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
