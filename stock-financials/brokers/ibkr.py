"""Interactive Brokers Client Portal API positions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests

from config import (
    IBKR_ACCOUNT_ID,
    IBKR_CPAPI_URL,
    IBKR_CSV_PATH,
    IBKR_ENABLED,
    IBKR_VERIFY_SSL,
)

logger = logging.getLogger(__name__)


def _parse_date(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    return text


def _row(
    *,
    ticker: str,
    full_name: str,
    currency: str,
    shares: Any,
    open_date: Any,
    buy_price: Any,
    total_fees: Any,
) -> dict[str, Any]:
    return {
        "Ticker": str(ticker).strip().upper(),
        "Full Name": full_name or None,
        "Source": "ibkr",
        "Currency": currency or None,
        "Shares": shares,
        "Open Date": _parse_date(open_date),
        "Buy Price": buy_price,
        "Total Fees": total_fees,
    }


def _cpapi_get(path: str) -> Any:
    url = f"{IBKR_CPAPI_URL.rstrip('/')}/{path.lstrip('/')}"
    resp = requests.get(url, verify=IBKR_VERIFY_SSL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _ensure_authenticated() -> None:
    status = _cpapi_get("iserver/auth/status")
    if isinstance(status, dict) and status.get("authenticated"):
        return
    raise RuntimeError(
        "IBKR Client Portal not authenticated. Log in at "
        "https://localhost:5000 (or your gateway), then retry."
    )


def _default_account_id() -> str:
    accounts = _cpapi_get("portfolio/accounts")
    if isinstance(accounts, list) and accounts:
        first = accounts[0]
        if isinstance(first, dict):
            return str(first.get("accountId") or first.get("id") or "")
        return str(first)
    if isinstance(accounts, dict):
        return str(accounts.get("accountId") or accounts.get("id") or "")
    raise ValueError("No IBKR accounts returned from /portfolio/accounts")


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


def _positions_from_ibkr(account_id: str) -> list[dict[str, Any]]:
    _ensure_authenticated()
    page = 0
    rows: list[dict[str, Any]] = []
    while True:
        data = _cpapi_get(
            f"portfolio/{account_id}/positions/{page}"
        )
        if not data:
            break
        items = data if isinstance(data, list) else data.get("positions", [])
        if not items:
            break
        for pos in items:
            if not isinstance(pos, dict):
                continue
            ticker = (
                pos.get("ticker")
                or pos.get("contractDesc")
                or pos.get("description")
                or ""
            )
            if not str(ticker).strip():
                continue
            rows.append(
                _row(
                    ticker=ticker,
                    full_name=pos.get("description") or pos.get("contractDesc"),
                    currency=pos.get("currency") or pos.get("cur"),
                    shares=pos.get("position") or pos.get("quantity"),
                    open_date=pos.get("openDate") or pos.get("open_date"),
                    buy_price=pos.get("avgCost")
                    or pos.get("avgPrice")
                    or pos.get("costBasis"),
                    total_fees=pos.get("fees") or pos.get("commissions"),
                )
            )
        page += 1
        if len(items) < 100:
            break
    return rows


def fetch_ibkr_positions() -> list[dict[str, Any]]:
    if not IBKR_ENABLED:
        return []

    if IBKR_CSV_PATH and IBKR_CSV_PATH.exists():
        logger.info("IBKR: loading positions from CSV %s", IBKR_CSV_PATH)
        return _from_csv(IBKR_CSV_PATH)

    account_id = IBKR_ACCOUNT_ID or _default_account_id()
    logger.info("IBKR: fetching positions for account %s", account_id)
    return _positions_from_ibkr(account_id)
