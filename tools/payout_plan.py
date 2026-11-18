#!/usr/bin/env python3
"""Daily payout planner (D46, #315). Pure: no network, no keys, no clock.

Turns a holder snapshot plus the system wallet's basket balances into `payout-plan.json`
(shared contract in #314). Per basket mint:

1. `carry-in` amounts are already inside the system wallet's balance. What is left
   (`balance - carry-in`) is today's new budget, split by D43 reward weight
   (balance x loyalty multiplier, `engine.rewards.allocate_holder_rewards`).
2. Each holder's accrued amount (carry-in + credit) is paid only if it is worth at least the
   token-account rent (D43 dust floor, `engine.rewards.settle_daily_rewards`); otherwise it is
   carried. Budget nobody can earn (no one held >= 1h) is carried on the system wallet.
3. Excluded wallets (team|system|pool|burn|cex) earn nothing; their old carry goes back to the
   budget. Invariant per mint: paid + carried == accrued == the mint's balance.

Same inputs give the same bytes.

    uv run python tools/payout_plan.py --snapshot snap.json --balances balances.json \
        --exclude exclude.json --carry-in carry.json --day 2026-11-19 --out plan.json

Input formats (amounts are base-unit integers, as strings or ints):
- snapshot: {"wallets": [{"address", "balance", "holding_seconds", "excluded_reason"?}]}
  (a bare list also works; extra wallet-export fields are ignored)
- balances: {"system_wallet": pk, "mints": {mint: {"amount": "1000",
  "price_lamports": "num/den"}}}; price = lamports per base unit, used for the dust floor
- exclude: {wallet: reason} or [{"wallet", "reason"}]
- carry-in: a previous plan (its "carried") or a list [{"wallet", "mint", "amount"}]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.rewards import (  # noqa: E402
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    allocate_holder_rewards,
    settle_daily_rewards,
)

SCHEMA = 1
MEMO_PREFIX = "GTASP10"
REASONS = frozenset({"team", "system", "pool", "burn", "cex"})


def memo_key(day: str, wallet: str, mint: str) -> str:
    return f"{MEMO_PREFIX}:pay:{day}:{wallet}:{mint}"


def _amount(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{what}: amount must be an integer or an integer string")
    if isinstance(value, str) and not value.isdigit():
        raise ValueError(f"{what}: bad amount {value!r}")
    n = int(value)
    if n < 0:
        raise ValueError(f"{what}: bad amount {value!r}")
    return n


def _price(value: Any, mint: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{mint}: price_lamports must be an int or 'num/den' string")
    p = Fraction(value)
    if p < 0:
        raise ValueError(f"{mint}: price_lamports must be >= 0")
    return p


def build_plan(
    *,
    day: str,
    snapshot: Any,
    balances: Mapping[str, Any],
    exclude: Any = None,
    carry_in: Any = None,
    min_payout_lamports: int = TOKEN_ACCOUNT_RENT_LAMPORTS,
) -> dict[str, Any]:
    """The plan dict in the #314 contract. Raises ValueError on inconsistent inputs."""
    day_index = dt.date.fromisoformat(day).toordinal()
    system = balances["system_wallet"]
    if not isinstance(system, str) or not system:
        raise ValueError("balances.system_wallet required")

    excluded: dict[str, str] = {system: "system"}
    rows = exclude.items() if isinstance(exclude, Mapping) else []
    if isinstance(exclude, list):
        rows = [(r["wallet"], r["reason"]) for r in exclude]
    for wallet, reason in rows:
        if reason not in REASONS:
            raise ValueError(f"exclude {wallet}: reason {reason!r} not in {sorted(REASONS)}")
        excluded.setdefault(wallet, reason)

    wallets = snapshot["wallets"] if isinstance(snapshot, Mapping) else snapshot
    held: dict[str, int] = {}
    hold_s: dict[str, int] = {}
    for rec in wallets:
        addr = rec["address"]
        if addr in held:
            raise ValueError(f"snapshot: duplicate wallet {addr}")
        reason = rec.get("excluded_reason")
        if reason:
            if reason not in REASONS:
                raise ValueError(f"snapshot {addr}: reason {reason!r} not in {sorted(REASONS)}")
            excluded.setdefault(addr, reason)
        held[addr] = _amount(rec["balance"], addr)
        hold_s[addr] = _amount(rec["holding_seconds"], addr)
    for addr in excluded:
        held.pop(addr, None)
        hold_s.pop(addr, None)

    if isinstance(carry_in, Mapping):
        carry_in = carry_in.get("carried", [])
    carry: dict[str, dict[str, int]] = {}
    for row in carry_in or []:
        per = carry.setdefault(row["mint"], {})
        per[row["wallet"]] = per.get(row["wallet"], 0) + _amount(row["amount"], row["wallet"])

    transfers: list[dict[str, str]] = []
    carried: list[dict[str, str]] = []
    totals: dict[str, dict[str, str]] = {}
    for mint in sorted(set(balances["mints"]) | set(carry)):
        info = balances["mints"].get(mint)
        if info is None:
            raise ValueError(f"carry-in for {mint} but no balance for it")
        accrued = _amount(info["amount"], mint)
        price = _price(info["price_lamports"], mint)
        mint_carry = carry.get(mint, {})
        # Old carry of wallets now excluded (or the system's unallocated budget) is re-split.
        keep = {w: a for w, a in mint_carry.items() if w not in excluded and a}
        budget = accrued - sum(keep.values())
        if budget < 0:
            raise ValueError(f"{mint}: carry-in {sum(keep.values())} > balance {accrued}")
        credit = allocate_holder_rewards(budget, held, hold_s)
        unallocated = budget - sum(credit.values())
        worth = {
            w: _floor(price * (keep.get(w, 0) + credit.get(w, 0))) for w in set(keep) | set(credit)
        }
        res = settle_daily_rewards(
            keep,
            {w: a for w, a in credit.items() if a},
            worth,
            day_index=day_index,
            min_payout_lamports=min_payout_lamports,
        )
        left = dict(res.carry)
        if unallocated:
            left[system] = unallocated
        paid = sum(res.paid.values())
        if paid + sum(left.values()) != accrued:  # pragma: no cover - invariant
            raise AssertionError(f"{mint}: conservation violated")
        for w, a in sorted(res.paid.items()):
            transfers.append(
                {"wallet": w, "mint": mint, "amount": str(a), "memo": memo_key(day, w, mint)}
            )
        for w, a in sorted(left.items()):
            carried.append({"wallet": w, "mint": mint, "amount": str(a)})
        totals[mint] = {
            "accrued": str(accrued),
            "paid": str(paid),
            "carried": str(accrued - paid),
        }

    return {
        "schema": SCHEMA,
        "day": day,
        "system_wallet": system,
        "transfers": sorted(transfers, key=lambda t: (t["wallet"], t["mint"])),
        "carried": sorted(carried, key=lambda t: (t["wallet"], t["mint"])),
        "excluded": [{"wallet": w, "reason": r} for w, r in sorted(excluded.items())],
        "totals": totals,
    }


def _floor(x: Fraction) -> int:
    return x.numerator // x.denominator


def dumps(plan: Mapping[str, Any]) -> str:
    return json.dumps(plan, indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--balances", type=Path, required=True)
    ap.add_argument("--exclude", type=Path)
    ap.add_argument("--carry-in", type=Path)
    ap.add_argument("--day", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-payout-lamports", type=int, default=TOKEN_ACCOUNT_RENT_LAMPORTS)
    a = ap.parse_args(argv)

    def load(p: Path | None) -> Any:
        return json.loads(p.read_text()) if p else None

    plan = build_plan(
        day=a.day,
        snapshot=load(a.snapshot),
        balances=load(a.balances),
        exclude=load(a.exclude),
        carry_in=load(a.carry_in),
        min_payout_lamports=a.min_payout_lamports,
    )
    tmp = a.out.with_name(a.out.name + ".tmp")
    tmp.write_text(dumps(plan))
    tmp.replace(a.out)
    n = len(plan["transfers"])
    print(f"{a.out}: {n} transfers, {len(plan['carried'])} carried, day {a.day}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
