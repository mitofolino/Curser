"""Market / listing exchange labels for portfolio Source column."""

from __future__ import annotations

import re
from typing import Any

# Yahoo-style suffix → common exchange name
_TICKER_SUFFIX_EXCHANGE: dict[str, str] = {
    "DE": "XETRA",
    "L": "LSE",
    "HK": "HKEX",
    "PA": "EURONEXT",
    "TO": "TSX",
    "AX": "ASX",
    "SW": "SIX",
    "T": "TSE",
    "TW": "TWSE",
    "KS": "KRX",
    "SI": "SGX",
    "MU": "GETTEX",
    "AS": "EURONEXT",
    "BR": "B3",
    "MX": "BMV",
    "SS": "SSE",
    "SZ": "SZSE",
    "KQ": "KOSDAQ",
    "VI": "VSE",
    "BC": "BCS",
    "SN": "SSE",
}

_SUFFIX_RE = re.compile(
    r"\.(" + "|".join(_TICKER_SUFFIX_EXCHANGE) + r")$",
    re.IGNORECASE,
)

# eToro / vendor aliases → display name
_ALIASES: dict[str, str] = {
    "XETRA": "XETRA",
    "FWB": "FWB",
    "GETTEX": "GETTEX",
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "ARCA": "ARCA",
    "BATS": "BATS",
    "AMEX": "AMEX",
    "LSE": "LSE",
    "HKEX": "HKEX",
    "HK": "HKEX",
    "TSE": "TSE",
    "TSX": "TSX",
    "ASX": "ASX",
    "SIX": "SIX",
}

# Listing exchange → trading currency (Source drives Currency)
EXCHANGE_CURRENCY: dict[str, str] = {
    "NASDAQ": "USD",
    "NYSE": "USD",
    "ARCA": "USD",
    "BATS": "USD",
    "AMEX": "USD",
    "XETRA": "EUR",
    "FWB": "EUR",
    "GETTEX": "EUR",
    "EURONEXT": "EUR",
    "LSE": "GBP",
    "HKEX": "HKD",
    "TSE": "JPY",
    "TWSE": "TWD",
    "KRX": "KRW",
    "KOSDAQ": "KRW",
    "SGX": "SGD",
    "ASX": "AUD",
    "TSX": "CAD",
    "SIX": "CHF",
    "SSE": "CNY",
    "SZSE": "CNY",
    "B3": "BRL",
    "BMV": "MXN",
    "VSE": "EUR",
    "BCS": "CLP",
}

# eToro / LSE report GBP instrument prices in pence (100 pence = £1)
GBP_PENCE_PER_POUND = 100


def normalize_local_buy_price(price: Any, currency: str | None) -> Any:
    """
    Convert broker buy/open rates from pence to pounds when currency is GBP.

    eToro ``openRate`` for LSE (and similar) is in pence; portfolio [local]
    columns and investment math use pounds.
    """
    if price is None or price == "":
        return price
    cur = _normalize_currency_code(currency)
    if cur != "GBP":
        return price
    try:
        return float(price) / GBP_PENCE_PER_POUND
    except (TypeError, ValueError):
        return price


def normalize_market_source(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    text = str(value).strip().upper()
    if text in _ALIASES:
        return _ALIASES[text]
    if text.startswith("LSE"):
        return "LSE"
    if "XETRA" in text or text in ("FWB", "GETTEX"):
        return "XETRA" if "XETRA" in text else text
    if "EURONEXT" in text or text == "PARIS":
        return "EURONEXT"
    if "NASDAQ" in text:
        return "NASDAQ"
    if "NYSE" in text:
        return "NYSE"
    return text


def exchange_from_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    match = _SUFFIX_RE.search(str(ticker).strip().upper())
    if not match:
        return None
    return _TICKER_SUFFIX_EXCHANGE.get(match.group(1).upper())


def _normalize_currency_code(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    from fx_rates import normalize_currency

    return normalize_currency(str(value).strip())


def currency_for_market_source(
    market: str | None,
    *,
    ticker: str | None = None,
    fallback: str | None = None,
) -> str | None:
    """
    Currency implied by listing exchange (Source).
    Source wins over broker-reported currency when both are present.
    """
    market = normalize_market_source(market)
    if market and market in EXCHANGE_CURRENCY:
        return EXCHANGE_CURRENCY[market]

    inferred = exchange_from_ticker(ticker)
    if inferred and inferred in EXCHANGE_CURRENCY:
        return EXCHANGE_CURRENCY[inferred]

    return _normalize_currency_code(fallback)
