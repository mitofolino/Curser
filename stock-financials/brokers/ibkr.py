"""Interactive Brokers positions via ib_insync (TWS / IB Gateway API)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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


def _format_open_datetime(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _parse_open_datetime(value: Any) -> str | None:
    """Normalize open date/time to UTC ``YYYY-MM-DD HH:MM:SS`` (portfolio column)."""
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
    if len(text) >= 10 and text[4] == "-":
        return text[:10] + " 00:00:00" if len(text) == 10 else text[:19]
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


def _extract_position_id(pos: Any) -> str | None:
    """IBKR contract id (conId), prefixed with account when available."""
    contract = getattr(pos, "contract", None)
    if contract is None:
        return None
    con_id = getattr(contract, "conId", None)
    if con_id is None:
        return None
    account = (getattr(pos, "account", None) or "").strip()
    return f"{account}:{con_id}" if account else str(con_id)


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
    used_platform: str | None = None,
    position_id: str | None = None,
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
        "Buy Price": normalize_gbp_pence_to_pounds(buy_price, resolved_currency),
        "Total Fees": normalize_gbp_pence_to_pounds(total_fees, resolved_currency),
        "Used Platform": used_platform,
        "Position ID": position_id,
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
                    used_platform=raw.get("Used Platform")
                    or raw.get("Platform")
                    or "IBKR",
                    position_id=(
                        raw.get("Position ID")
                        or raw.get("PositionID")
                        or raw.get("conId")
                        or raw.get("ConId")
                    ),
                )
            )
    return rows


def _execution_filter_candidates(account: str) -> list[Any]:
    """
    Build ExecutionFilter attempts for reqExecutions.

    TWS usually only returns recent executions (often since midnight). Also match
    the API client id — trades may not appear when clientId stays 0.
    """
    from ib_insync import ExecutionFilter

    candidates: list[Any] = []
    for client_id in (IBKR_CLIENT_ID, 0):
        if account:
            f = ExecutionFilter()
            f.acctCode = account
            f.clientId = client_id
            candidates.append(f)
        f_all = ExecutionFilter()
        f_all.clientId = client_id
        candidates.append(f_all)
    candidates.append(ExecutionFilter())
    return candidates


def _fill_sort_key(fill: Any) -> datetime:
    ex = fill.execution
    t = fill.time or getattr(ex, "time", None)
    if isinstance(t, datetime):
        return t
    return datetime.min.replace(tzinfo=timezone.utc)


def _holding_open_datetime(fills: list[Any], *, is_long: bool) -> datetime | None:
    """
    Replay BOT/SLD fills to find when the current long (or short) holding started.
    """
    eps = 1e-6
    position = 0.0
    open_time: datetime | None = None

    for fill in sorted(fills, key=_fill_sort_key):
        ex = fill.execution
        side = (getattr(ex, "side", None) or "").upper()
        shares = float(getattr(ex, "shares", 0) or 0)
        if shares <= 0:
            continue

        if side in ("BOT", "BUY"):
            delta = shares
        elif side in ("SLD", "SELL"):
            delta = -shares
        else:
            continue

        prev = position
        position += delta
        t = fill.time or getattr(ex, "time", None)

        if is_long:
            if prev <= eps and position > eps and isinstance(t, datetime):
                open_time = t
            if position <= eps:
                position = 0.0
                open_time = None
        else:
            if prev >= -eps and position < -eps and isinstance(t, datetime):
                open_time = t
            if position >= -eps:
                position = 0.0
                open_time = None

    if is_long and position > eps:
        return open_time
    if not is_long and position < -eps:
        return open_time
    return None


def _fills_by_account_conid(fills: list[Any]) -> dict[tuple[str, int], list[Any]]:
    by_key: dict[tuple[str, int], list[Any]] = {}
    for fill in fills:
        contract = fill.contract
        con_id = getattr(contract, "conId", None)
        if con_id is None:
            continue
        acct = (getattr(fill.execution, "acctNumber", None) or "").strip()
        key = (acct, int(con_id))
        by_key.setdefault(key, []).append(fill)
    return by_key


def _fills_by_conid(fills: list[Any]) -> dict[int, list[Any]]:
    by_conid: dict[int, list[Any]] = {}
    for fill in fills:
        con_id = getattr(fill.contract, "conId", None)
        if con_id is None:
            continue
        by_conid.setdefault(int(con_id), []).append(fill)
    return by_conid


def _dedupe_fills(fills: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for fill in fills:
        exec_id = getattr(fill.execution, "execId", None) or ""
        if exec_id and exec_id in seen:
            continue
        if exec_id:
            seen.add(exec_id)
        out.append(fill)
    return out


def _collect_execution_fills(ib: Any, account_filter: str) -> list[Any]:
    """Merge fills from TWS connect sync, reqExecutions, and completed orders."""
    collected: list[Any] = []

    sync_fills = list(ib.fills())
    collected.extend(sync_fills)
    logger.info("IBKR: %d fill(s) from TWS connect sync", len(sync_fills))

    for filt in _execution_filter_candidates(account_filter):
        try:
            collected.extend(ib.reqExecutions(filt))
            ib.sleep(0.2)
        except Exception as e:
            logger.debug("IBKR reqExecutions failed: %s", e)

    if not IBKR_READONLY:
        try:
            for trade in ib.reqCompletedOrders(False):
                collected.extend(trade.fills)
            ib.sleep(0.2)
            logger.info("IBKR: included fills from reqCompletedOrders")
        except Exception as e:
            logger.debug("IBKR reqCompletedOrders failed: %s", e)
    else:
        logger.info(
            "IBKR: IBKR_READONLY=true skips reqCompletedOrders "
            "(set false to load more trade history for open dates)"
        )

    fills = _dedupe_fills(collected)
    logger.info("IBKR: %d unique execution fill(s) for open-date lookup", len(fills))
    return fills


def _open_date_for_position(
    fills: list[Any], *, quantity: float
) -> str | None:
    if not fills or abs(quantity) < 1e-6:
        return None
    open_dt = _holding_open_datetime(fills, is_long=quantity > 0)
    if open_dt is None:
        return None
    return _format_open_datetime(open_dt)


def _resolve_open_date(
    *,
    fills_by_acct: dict[tuple[str, int], list[Any]],
    fills_by_conid: dict[int, list[Any]],
    account: str,
    con_id: int,
    quantity: float,
) -> str | None:
    group = fills_by_acct.get((account, con_id), [])
    if not group:
        group = fills_by_conid.get(con_id, [])
    return _open_date_for_position(group, quantity=quantity)


def _positions_from_ib_insync() -> list[dict[str, Any]]:
    from ib_insync import IB

    ib = IB()
    try:
        connect_account = IBKR_ACCOUNT_ID.strip() if IBKR_ACCOUNT_ID else ""
        ib.connect(
            IBKR_HOST,
            IBKR_PORT,
            clientId=IBKR_CLIENT_ID,
            readonly=IBKR_READONLY,
            timeout=IBKR_CONNECT_TIMEOUT,
            account=connect_account,
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

        fills = _collect_execution_fills(ib, account_filter)
        fills_by_acct = _fills_by_account_conid(fills)
        fills_by_conid = _fills_by_conid(fills)
        missing_dates = 0

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
            acct = (getattr(pos, "account", None) or "").strip()
            con_id = getattr(contract, "conId", None)
            open_date = None
            if con_id is not None:
                open_date = _resolve_open_date(
                    fills_by_acct=fills_by_acct,
                    fills_by_conid=fills_by_conid,
                    account=acct,
                    con_id=int(con_id),
                    quantity=qty,
                )
            if not open_date:
                missing_dates += 1
            # IB reports avgCost as total cost per share in contract currency (not pence)
            rows.append(
                _row(
                    ticker=ticker,
                    full_name=long_name,
                    source=_contract_market_source(contract),
                    currency=getattr(contract, "currency", None),
                    shares=qty,
                    open_date=open_date,
                    buy_price=avg_cost,
                    total_fees=0.0,
                    used_platform="IBKR",
                    position_id=_extract_position_id(pos),
                )
            )

        if missing_dates:
            logger.warning(
                "IBKR: no open date for %d position(s). TWS API only returns "
                "recent executions; preserve dates in the sheet, set "
                "IBKR_CSV_PATH, or IBKR_READONLY=false and re-run.",
                missing_dates,
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
