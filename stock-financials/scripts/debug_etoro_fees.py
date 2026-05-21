#!/usr/bin/env python3
"""Print raw eToro portfolio fee fields (one-off debug)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brokers.etoro import _api_get, _positions_from_portfolio_payload, PORTFOLIO_PATH


def main() -> int:
    payload = _api_get(PORTFOLIO_PATH.lstrip("/"))
    positions = _positions_from_portfolio_payload(payload)
    print(f"positions: {len(positions)}")
    for p in positions:
        if not isinstance(p, dict):
            continue
        fee_fields = {
            k: p[k]
            for k in p
            if "fee" in k.lower() or "commission" in k.lower() or "cost" in k.lower()
        }
        if not fee_fields:
            continue
        tf = p.get("totalFees")
        te = p.get("totalExternalFees")
        tt = p.get("totalExternalTaxes")
        combined = float(tf or 0) + float(te or 0)
        print(
            f"ID{p.get('instrumentID')}: totalFees={tf!r} "
            f"totalExternalFees={te!r} totalExternalTaxes={tt!r} "
            f"wrong_sum={combined}"
        )
        extra = {k: v for k, v in fee_fields.items() if k not in ("totalFees", "totalExternalFees")}
        if extra:
            print(f"  other: {extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
