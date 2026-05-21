"""Interactive Brokers positions via ib_insync (TWS / IB Gateway API)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from config import (
    IBKR_ACCOUNT_ID,
    IBKR_CLIENT_ID,
    IBKR_CONNECT_TIMEOUT,
    IBKR_CSV_PATH,
    IBKR_ENABLED,
    IBKR_HOST,
    IBKR_PORT,
    IBKR_READONLY,
)
from market_source import (
    currency_for_market_source,
    exchange_from_ticker,
    normalize_gbp_pence_to_pounds,
    normalize_market_source,
)

logger = logging.getLogger(__name__)

# IB primaryExchange / exchange → Yahoo-style ticker suffix
_IB_EXCHANGE_TICKER_SUFFIX: dict[str, str] = {
    "LSE": "L",
    "IBE": "L",
    "IBIS": "DE",
    "IBIS2": "DE",
    "XETRA": "DE",
    "FWB": "DE",
    "GETTEX": "DE",
    "SWX": "SW",
    "EBS": "SW",
    "SFB": "SW",
    "TSEJ": "T",
    "TSE": "T",
    "SEHK": "HK",
    "HKEX": "HK",
    "ASX": "AX",
    "TSX": "TO",
    "EURONEXT": "PA",
    "AEB": "AS",
    "BVME": "MI",
    "BME": "MC",
    "SBF": "PA",
    "MIL": "MI",
}


def _parse_date(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    return text


def _contract_market_source(contract: Any) -> str | None:
    for attr in ("primaryExchange", "exchange"):
        val = getattr(contract, attr, None)
        if val and str(val).strip():
            return normalize_market_source(str(val))
    return None


def _contract_to_ticker(contract: Any) -> str:
    symbol = (getattr(contract, "symbol", None) or "").strip().upper()
    if not symbol:
        return ""

    local = (getattr(contract, "localSymbol", None) or "").strip().upper()
    if local and local != symbol and "." in local:
        return local

    pe = (getattr(contract, "primaryExchange", None) or "").strip().upper()
    exch = (getattr(contract, "exchange", None) or "").strip().upper()
    key = pe or exch

    suffix = _IB_EXCHANGE_TICKER_SUFFIX.get(key)
    if suffix and not symbol.endswith(f".{suffix}"):
        return f"{symbol}.{suffix}"

    inferred = exchange_from_ticker(symbol)
    if inferred and key in ("SMART", "") and "." not in symbol:
        return symbol

    return symbol


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
        "Open Date": _parse_date(open_date),
        "Buy Price": normalize_gbp_pence_to_pounds(buy_price, resolved_currency),
        "Total Fees": normalize_gbp_pence_to_pounds(total_fees, resolved_currency),
    }


def _from_csv(path) -> list[dict[str, Any]]:
    import csv

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            ticker = raw.get("Ticker") or raw.get("Symbol") or ""
            if not str(ticker).strip():
                continue
            rows.append(
                _row(
                    ticker=ticker,
                    full_name=raw.get("Full Name") or raw.get("Description"),
                    source=raw.get("Source")
                    or raw.get("Exchange")
                    or raw.get("Listing Exchange"),
                    currency=raw.get("Currency"),
                    shares=raw.get("Shares") or raw.get("Quantity"),
                    open_date=raw.get("Open Date") or raw.get("OpenDate"),
                    buy_price=raw.get("Buy Price")
                    or raw.get("Cost Basis Price")
                    or raw.get("Avg Price"),
                    total_fees=raw.get("Total Fees") or raw.get("Commissions"),
                )
            )
    return rows


def _positions_from_ib_insync() -> list[dict[str, Any]]:
    from ib_insync import IB

    ib = IB()
    try:
        ib.connect(
            IBKR_HOST,
            IBKR_PORT,
            clientId=IBKR_CLIENT_ID,
            readonly=IBKR_READONLY,
            timeout=IBKR_CONNECT_TIMEOUT,
        )
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to TWS/IB Gateway at {IBKR_HOST}:{IBKR_PORT} "
            f"(clientId={IBKR_CLIENT_ID}): {e}"
        ) from e

    try:
        accounts = ib.managedAccounts()
        logger.info("IBKR connected; accounts: %s", ", ".join(accounts) or "(none)")

        account_filter = IBKR_ACCOUNT_ID.strip() if IBKR_ACCOUNT_ID else ""
        ib.sleep(0.5)
        positions = ib.positions()
        if positions:
            ib.qualifyContracts(*(p.contract for p in positions))
        if account_filter:
            positions = [p for p in positions if p.account == account_filter]

        rows: list[dict[str, Any]] = []
        for pos in positions:
            qty = float(pos.position)
            if qty == 0:
                continue

            contract = pos.contract
            sec_type = (getattr(contract, "secType", None) or "").upper()
            if sec_type and sec_type not in ("STK", "ETF", "FOP", "OPT", "WAR"):
                logger.debug(
                    "IBKR: skip %s position in %s",
                    sec_type,
                    getattr(contract, "symbol", ""),
                )
                continue

            ticker = _contract_to_ticker(contract)
            if not ticker:
                continue

            long_name = getattr(contract, "longName", None) or getattr(
                contract, "description", None
            )
            avg_cost = float(pos.avgCost) if pos.avgCost else None
            # IB reports avgCost as total cost per share in contract currency (not pence)
            rows.append(
                _row(
                    ticker=ticker,
                    full_name=long_name,
                    source=_contract_market_source(contract),
                    currency=getattr(contract, "currency", None),
                    shares=qty,
                    open_date=None,
                    buy_price=avg_cost,
                    total_fees=0.0,
                )
            )

        logger.info(
            "IBKR ib_insync: %d position(s) from %s:%s",
            len(rows),
            IBKR_HOST,
            IBKR_PORT,
        )
        return rows
    finally:
        if ib.isConnected():
            ib.disconnect()


def fetch_ibkr_positions() -> list[dict[str, Any]]:
    if not IBKR_ENABLED:
        return []

    if IBKR_CSV_PATH and IBKR_CSV_PATH.exists():
        logger.info("IBKR: loading positions from CSV %s", IBKR_CSV_PATH)
        return _from_csv(IBKR_CSV_PATH)

    return _positions_from_ib_insync()
