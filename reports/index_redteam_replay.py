"""Synthetic replay of INDEX_RULES v0.1 filters against attacker metrics.

Runs against the pure ``index/`` code merged on ``main``. No network, no wallets, no chain
writes. Evidence for ``reports/index_redteam_2026-11-18.md``.

Run from the repo root::

    uv run python reports/index_redteam_replay.py

An abridged excerpt is in §9 of the report; run the script for the full output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import base58

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from index.filters import (  # noqa: E402
    Metrics,
    candidate_status,
    first_failed_filter,
    log_score,
)
from index.params import IndexParams, Overrides  # noqa: E402
from index.select import run_index, split_prize, weights_bps  # noqa: E402

AS_OF = "2026-11-17T18:00:00Z"  # replay, not a real rebalance


def mint(n: int) -> str:
    return base58.b58encode(bytes([n]) * 32).decode()


PARAMS = IndexParams.model_validate(json.loads((ROOT / "index/params.json").read_text()))
OVERRIDES = Overrides.model_validate(json.loads((ROOT / "index/overrides.json").read_text()))


def base(m: str, ticker: str, name: str, **kw) -> Metrics:
    vals = dict(
        mint=m,
        ticker=ticker,
        name=name,
        description="",
        coverage=1.0,
        age_hours=48.0,
        liquidity_usd=150_000.0,
        mc_usd=2_000_000.0,
        top10_pct=20.0,
        total_fees_sol=12.0,
        window_fees_sol=12.0,
        bundle_pct=0.0,
        dev_pct=2.0,
        creator_launches_7d=2,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=250,
        volume_usd=300_000.0,
    )
    vals.update(kw)
    return Metrics(**vals)


LEGIT = base(mint(1), "LEGIT", "Grand Theft Auto 6 Army")
SYBIL = base(mint(2), "SYBIL", "GTA 6 Official", volume_usd=100_000.0)
LOWFLOAT = base(
    mint(3),
    "FLOAT",
    "GTA 6 Vice City",
    mc_usd=50_000_000.0,
    liquidity_usd=50_000.0,
    total_fees_sol=10.0,
    window_fees_sol=10.0,
    unique_traders=200,
    volume_usd=2_500_000.0,
)
REBRAND = base(
    mint(4),
    "REBRAND",
    "GTA 6",
    mc_usd=8_000_000.0,
    liquidity_usd=400_000.0,
    volume_usd=800_000.0,
)
T22 = base(mint(5), "T22", "GTA 6 Hook", mc_usd=5_000_000.0)
FILLERS = [
    base(mint(10 + i), f"FILL{i}", "GTA 6 Filler", mc_usd=1_000_000.0 + i * 100_000.0)
    for i in range(5)
]
ALL = [LEGIT, SYBIL, LOWFLOAT, REBRAND, T22, *FILLERS]


def main() -> None:
    print("== filter/score checks ==")
    for m in ALL:
        print(
            f"{m.ticker:8s} first_failed={str(first_failed_filter(m, PARAMS)):6s} "
            f"status={str(candidate_status(m, PARAMS, OVERRIDES)):10s} logS={log_score(m, PARAMS)}"
        )

    print("\n== rebalance with ten candidates (self_mint is null in params.json) ==")
    out = run_index(ALL, [], PARAMS, OVERRIDES, AS_OF, "replay")
    for row in out["members"]:
        print(
            f"rank {row['rank']:2d} {row['ticker']:8s} logS={row['log_s']:.6f} "
            f"bps={row['weight_bps']:5d} mc={row['metrics']['mc_usd']:.0f} "
            f"liq={row['metrics']['liquidity_usd']:.0f}"
        )
    print("excluded:", out["excluded"])
    print("dry_run:", out["dry_run"], "skipped:", out["skipped_filters"])

    print("\n== self_mint guard ==")
    print("params.self_mint =", PARAMS.self_mint)
    print("status of SYBIL with self_mint=null:", candidate_status(SYBIL, PARAMS, OVERRIDES))
    p_self = PARAMS.model_copy(update={"self_mint": SYBIL.mint})
    print("status of SYBIL with self_mint=SYBIL:", candidate_status(SYBIL, p_self, OVERRIDES))

    print("\n== dry_run skipped F4 (no fee source) ==")
    no_fee = base(mint(6), "NOFEE", "GTA 6 No Fees", total_fees_sol=0.0, window_fees_sol=1.0)
    print("F4 checked:", first_failed_filter(no_fee, PARAMS))
    p_skip = PARAMS.model_copy(
        update={"dry_run": PARAMS.dry_run.model_copy(update={"skip_filters": ("F4",)})}
    )
    out2 = run_index([no_fee], [], p_skip, OVERRIDES, AS_OF, "replay")
    print("F4 skipped:", first_failed_filter(no_fee, p_skip))
    print("dry_run:", out2["dry_run"], "members:", [m["ticker"] for m in out2["members"]])

    print("\n== weights / prize rounding at dust ==")
    bps = weights_bps([m.mint for m in ALL], {m.mint: log_score(m, PARAMS) for m in ALL}, PARAMS)
    print("bps:", {m.ticker: bps[m.mint] for m in ALL}, "sum:", sum(bps.values()))
    for prize in (1, 9_999, 10_000, 10_001):
        parts = split_prize(prize, [m.mint for m in ALL], bps)
        print(
            f"prize {prize:6d} -> rank1 {parts[ALL[0].mint]:6d}, "
            f"others {[parts[m.mint] for m in ALL[1:]]}"
        )

    print("\n== F3 boundary ==")
    for v in (12.999999, 13.0, 27.0, 27.000001):
        m = base(mint(7), "BOUND", "GTA 6 Bound", top10_pct=v)
        print(f"top10={v:10.6f} -> {first_failed_filter(m, PARAMS)}")

    print("\n== F10 boundary / turnover ==")
    for vol in (99_999.0, 100_000.0, 6_000_000.0, 6_000_001.0):
        m = base(mint(8), "TURN", "GTA 6 Turn", volume_usd=vol)
        print(
            f"volume={vol:10.0f} turnover={vol / m.mc_usd:.6f} -> {first_failed_filter(m, PARAMS)}"
        )


if __name__ == "__main__":
    main()
