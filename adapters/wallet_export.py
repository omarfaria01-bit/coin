"""Per-wallet JSON for the GTASP10 site (#273, D39). Read-only: no keys, no tx, no clock.

The site reads `/gtasp10/data/wallets/<address>.json`. Every number here comes from the engine
(`engine.scoring.h_of_age`, `engine.hourly_draw.draw_weights`); the page never recomputes them.
Nothing is written unless the caller asks: `build_wallet_records` is pure, `write_wallet_files`
does an atomic temp + rename per file.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from engine.hourly_draw import (
    CAP_DEFAULT,
    MIN_HOLDING_SHARE_DEFAULT,
    SUPPLY_CAP_DEFAULT,
    draw_weights,
    eligible_groups,
)
from engine.scoring import h_of_age
from engine.types import ClusterId

SCHEMA_VERSION = 1
_ODDS_DIGITS = 9


@dataclass(frozen=True)
class WalletInput:
    wallet: str
    cluster: ClusterId
    balance: int  # token base units
    holding_seconds: int  # age of the wallet's oldest still-held lot
    accrued: tuple[tuple[str, int, int], ...] = field(default=())  # (ticker, amount, usd_cents)


def _decimal(x: Fraction, digits: int = _ODDS_DIGITS) -> str:
    """Floor to `digits` decimals with integer math (no float)."""
    scaled = x.numerator * 10**digits // x.denominator
    whole, frac = divmod(scaled, 10**digits)
    return f"{whole}.{frac:0{digits}d}"


def build_wallet_records(
    wallets: Iterable[WalletInput],
    *,
    scores: Mapping[ClusterId, int | Fraction],
    cluster_balances: Mapping[ClusterId, int | Fraction],
    total_supply: int,
    excluded: Mapping[str, str],
    as_of: str,
    cap: Fraction = CAP_DEFAULT,
    supply_cap: Fraction = SUPPLY_CAP_DEFAULT,
    min_holding_share: Fraction = MIN_HOLDING_SHARE_DEFAULT,
) -> dict[str, dict[str, object]]:
    """address → record. Callers drop `excluded` wallets from `scores` and `cluster_balances`
    first (D39); odds are the cluster odds split by balance within the cluster."""
    if total_supply <= 0:
        raise ValueError("total_supply > 0")
    ok = eligible_groups(scores, cluster_balances, total_supply, min_holding_share)
    weights = draw_weights(
        {c: scores[c] for c in ok},
        cluster_balances,
        total_supply,
        cap=cap,
        supply_cap=supply_cap,
        min_holding_share=min_holding_share,
    )
    wsum = sum(weights.values())
    members = {}
    for w in wallets:
        members.setdefault(w.cluster, []).append(w)
    out: dict[str, dict[str, object]] = {}
    for cluster, group in members.items():
        gbal = sum(w.balance for w in group)
        for w in group:
            is_excl = w.wallet in excluded
            eligible = cluster in weights and not is_excl
            # The cluster's odds are split by balance so one wallet never shows the whole group's.
            odds = Fraction(0)
            if eligible and wsum > 0 and gbal > 0:
                odds = Fraction(weights[cluster], wsum) * Fraction(w.balance, gbal)
            mult = h_of_age(w.holding_seconds)
            out[w.wallet] = {
                "schema": SCHEMA_VERSION,
                "address": w.wallet,
                "as_of": as_of,
                "holding_seconds": w.holding_seconds,
                "supply_share": _decimal(Fraction(w.balance, total_supply)),
                "draw_odds": _decimal(odds),
                "multiplier": {
                    "exact": f"{mult.numerator}/{mult.denominator}",
                    "decimal": _decimal(mult, 4),
                },
                "eligible": eligible,
                "excluded_reason": excluded.get(w.wallet),
                "accrued": [
                    {"ticker": t, "amount": str(a), "usd": f"{usd // 100}.{usd % 100:02d}"}
                    for t, a, usd in w.accrued
                ],
            }
    return out


def write_wallet_files(records: Mapping[str, Mapping[str, object]], out_dir: Path) -> int:
    """Atomic temp + rename per `<address>.json`. Returns the number of files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for address, rec in records.items():
        if not address.isalnum():  # base58 only: never lets a name escape out_dir
            raise ValueError(f"refusing unsafe file name: {address!r}")
        fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
            os.replace(tmp, out_dir / f"{address}.json")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return len(records)
