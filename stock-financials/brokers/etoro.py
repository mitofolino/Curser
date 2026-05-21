"""eToro portfolio positions via Public API (x-api-key + x-user-key)."""

from __future__ import annotations

import csv
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from config import (
    ETORO_API_PRIVATE_KEY,
    ETORO_API_PUBLIC_KEY,
    ETORO_API_URL,
    ETORO_CSV_PATH,
    ETORO_ENABLED,
    ETORO_USER_KEY,
    OUTPUT_DIR,
)
from market_source import (
    currency_for_market_source,
    exchange_from_ticker,
    normalize_local_buy_price,
    normalize_market_source,
)

logger = logging.getLogger(__name__)

PORTFOLIO_PATH = "/trading/info/portfolio"


def _format_open_datetime(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _parse_open_datetime(value: Any) -> str | None:
    """Preserve date and time from eToro openDateTime (ISO-8601, UTC)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _format_open_datetime(value)

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        return _format_open_datetime(datetime.fromisoformat(normalized))
    except ValueError:
        pass

    if "T" in text and len(text) >= 19:
        return text[:10] + " " + text[11:19]
    if len(text) >= 10:
        return text[:10]
    return text


def _row(
    *,
    ticker: str,
    full_name: str,
    source: str | None,
    currency: str,
    shares: Any,
    open_date: Any,
    buy_price: Any,
    total_fees: Any,
) -> dict[str, Any]:
    market = normalize_market_source(source) or exchange_from_ticker(ticker)
    resolved_currency = currency_for_market_source(
        market, ticker=ticker, fallback=currency
    )
    return {
        "Ticker": str(ticker).strip().upper(),
        "Full Name": full_name or None,
        "Source": market,
        "Currency": resolved_currency,
        "Shares": shares,
        "Open Date": _parse_open_datetime(open_date),
        "Buy Price": normalize_local_buy_price(buy_price, resolved_currency),
        "Total Fees": total_fees,
    }


def _api_headers() -> dict[str, str]:
    if not ETORO_API_PUBLIC_KEY or not ETORO_USER_KEY:
        raise ValueError(
            "Set ETORO_API_PUBLIC_KEY and ETORO_API_PRIVATE_KEY (user key) in .env"
        )
    return {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": ETORO_API_PUBLIC_KEY,
        "x-user-key": ETORO_USER_KEY,
        "Content-Type": "application/json",
    }


_INSTRUMENT_LOOKUP_PATH = "/market-data/instruments"
# eToro returns 500 for comma-separated instrumentIds; fetch one ID per request.
_INSTRUMENT_REQUEST_DELAY = 0.35
_INSTRUMENT_CACHE_PATH = OUTPUT_DIR / ".etoro_instrument_cache.json"


def _api_get(path: str, *, params: dict[str, str] | None = None) -> Any:
    url = f"{ETORO_API_URL.rstrip('/')}/{path.lstrip('/')}"
    resp = _request("GET", url, params=params)
    return resp.json()


def _request(
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> requests.Response:
    last: requests.Response | None = None
    for attempt in range(4):
        headers = _api_headers()
        if method == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=60)
        else:
            resp = requests.post(
                url, headers=headers, json=json_body, timeout=60
            )
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        last = resp
        wait = min(2**attempt, 30)
        logger.warning("eToro rate limited (429); retry in %ss", wait)
        time.sleep(wait)
    if last is not None:
        last.raise_for_status()
    raise RuntimeError("eToro request failed without response")


def _parse_instrument_item(item: dict) -> dict[str, Any] | None:
    iid = item.get("instrumentID") or item.get("InstrumentID")
    if iid is None:
        return None
    symbol = (
        item.get("symbolFull")
        or item.get("internalSymbolFull")
        or item.get("symbol")
        or item.get("Symbol")
        or item.get("internalSymbol")
    )
    price_source = normalize_market_source(
        item.get("priceSource") or item.get("PriceSource")
    )
    api_currency = item.get("currency") or item.get("currencyCode")
    currency = currency_for_market_source(
        price_source, ticker=symbol, fallback=api_currency
    )
    return {
        "symbol": symbol,
        "name": item.get("instrumentDisplayName")
        or item.get("displayName")
        or item.get("name"),
        "currency": currency,
        "price_source": price_source,
    }


def _load_instrument_cache() -> dict[int, dict[str, Any]]:
    if not _INSTRUMENT_CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(_INSTRUMENT_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("eToro instrument cache unreadable: %s", e)
        return {}
    out: dict[int, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and value.get("symbol"):
            out[int(key)] = value
    return out


def _save_instrument_cache(mapping: dict[int, dict[str, Any]]) -> None:
    try:
        _INSTRUMENT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {str(k): v for k, v in sorted(mapping.items())}
        _INSTRUMENT_CACHE_PATH.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.debug("eToro instrument cache not saved: %s", e)


def _instrument_map(instrument_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Resolve instrumentID → symbol, name, currency."""
    if not instrument_ids:
        return {}

    mapping = _load_instrument_cache()
    to_fetch = sorted(
        iid
        for iid in instrument_ids
        if iid not in mapping or not mapping[iid].get("price_source")
    )

    for iid in to_fetch:
        try:
            payload = _api_get(
                _INSTRUMENT_LOOKUP_PATH,
                params={"instrumentIds": str(iid)},
            )
        except requests.HTTPError as e:
            logger.debug("eToro instrument %s lookup failed: %s", iid, e)
            continue

        items = []
        if isinstance(payload, dict):
            items = payload.get("instrumentDisplayDatas") or []
        if not items or not isinstance(items[0], dict):
            continue

        parsed = _parse_instrument_item(items[0])
        if parsed and parsed.get("symbol"):
            mapping[iid] = parsed

        if _INSTRUMENT_REQUEST_DELAY > 0:
            time.sleep(_INSTRUMENT_REQUEST_DELAY)

    if to_fetch:
        _save_instrument_cache(mapping)

    missing = instrument_ids - {k for k, v in mapping.items() if v.get("symbol")}
    if missing:
        logger.warning(
            "eToro: no symbol for %d instrument(s): %s",
            len(missing),
            ", ".join(f"ID{i}" for i in sorted(missing)[:5]),
        )

    return {iid: mapping[iid] for iid in instrument_ids if iid in mapping}


def _position_total_fees(pos: dict) -> float:
    """
    eToro ``totalFees`` is already in account currency (0 or negative).

    ``totalExternalFees`` is not a dollar amount (often 1.0 / 2.0 as a flag);
    adding it was turning fees positive. ``totalExternalTaxes`` is separate.
    """
    fees = float(pos.get("totalFees") or 0)
    taxes = pos.get("totalExternalTaxes")
    if taxes is not None:
        t = float(taxes)
        if t < 0:
            fees += t
        elif t > 0:
            fees -= t
    return fees


def _positions_from_portfolio_payload(payload: dict) -> list[dict]:
    client = payload.get("clientPortfolio") or payload.get("ClientPortfolio") or {}
    return client.get("positions") or client.get("Positions") or []


def _from_api() -> list[dict[str, Any]]:
    payload = _api_get(PORTFOLIO_PATH.lstrip("/"))
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected eToro portfolio response: {type(payload)}")

    positions = _positions_from_portfolio_payload(payload)
    if not positions:
        logger.warning("eToro: no open positions in portfolio response")
        return []

    instrument_ids = {
        int(p["instrumentID"])
        for p in positions
        if isinstance(p, dict) and p.get("instrumentID") is not None
    }
    instruments = _instrument_map(instrument_ids)

    rows: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        iid = pos.get("instrumentID")
        meta = instruments.get(int(iid), {}) if iid is not None else {}
        ticker = meta.get("symbol") or f"ID{iid}"
        if not str(ticker).strip():
            continue

        rows.append(
            _row(
                ticker=str(ticker),
                full_name=meta.get("name"),
                source=meta.get("price_source"),
                currency=meta.get("currency"),
                shares=pos.get("lotCount")
                or pos.get("units")
                or pos.get("initialUnits"),
                open_date=pos.get("openDateTime") or pos.get("openDate"),
                buy_price=pos.get("openRate") or pos.get("buyPrice"),
                total_fees=_position_total_fees(pos),
            )
        )
    return rows


def _from_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            ticker = (
                raw.get("Ticker")
                or raw.get("Symbol")
                or raw.get("Instrument")
                or ""
            )
            if not str(ticker).strip():
                continue
            rows.append(
                _row(
                    ticker=ticker,
                    full_name=raw.get("Full Name")
                    or raw.get("Name")
                    or raw.get("Instrument Name"),
                    source=raw.get("Source")
                    or raw.get("Exchange")
                    or raw.get("Market")
                    or raw.get("priceSource"),
                    currency=raw.get("Currency") or raw.get("Currency Code"),
                    shares=raw.get("Shares")
                    or raw.get("Units")
                    or raw.get("Quantity"),
                    open_date=raw.get("Open Date")
                    or raw.get("OpenDate")
                    or raw.get("Date"),
                    buy_price=raw.get("Buy Price")
                    or raw.get("Open Rate")
                    or raw.get("Avg. Open"),
                    total_fees=raw.get("Total Fees")
                    or raw.get("Fees")
                    or raw.get("Commission"),
                )
            )
    return rows


def fetch_etoro_positions() -> list[dict[str, Any]]:
    if not ETORO_ENABLED:
        return []

    if ETORO_CSV_PATH and ETORO_CSV_PATH.exists():
        logger.info("eToro: loading positions from CSV %s", ETORO_CSV_PATH)
        return _from_csv(ETORO_CSV_PATH)

    if ETORO_API_PUBLIC_KEY and ETORO_USER_KEY:
        rows = _from_api()
        logger.info("eToro API: fetched %d position(s)", len(rows))
        return rows

    logger.warning(
        "eToro: set ETORO_API_PUBLIC_KEY + ETORO_API_PRIVATE_KEY in .env, or ETORO_CSV_PATH"
    )
    return []
