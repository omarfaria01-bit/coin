"""index/emergency.py: removal between rebalances (INDEX_RULES §5, #156)."""

from __future__ import annotations

import json
from pathlib import Path

import base58
import pytest

from index.emergency import apply_emergency
from index.filters import Metrics
from index.params import IndexParams, Overrides
from index.select import canonical_json, run_index

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))


def mint(i: int) -> str:
    return base58.b58encode(i.to_bytes(2, "big") * 16).decode()


def coin(i: int) -> Metrics:
    mc = 1_000_000.0 + i * 10_000
    return Metrics(
        mint=mint(i),
        ticker=f"GTA{i}",
        name="GTA 6 coin",
        coverage=1.0,
        age_hours=30.0,
        liquidity_usd=100_000.0,
        mc_usd=mc,
        top10_pct=20.0,
        total_fees_sol=40.0,
        window_fees_sol=12.0,
        bundle_pct=2.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=500,
        independent_traders=500,
        roundtrip_share=0.0,
        volume_wallets=100,
        median_trade_sol=0.1,
        volume_usd=mc,
    )


BASE = run_index([coin(i) for i in range(12)], [], P, Overrides(), "2026-11-19T18:00:00Z", "abc")


def test_removal_recomputes_weights_and_logs() -> None:
    victim = BASE["members"][3]["mint"]
    out = apply_emergency(BASE, victim, "liquidity_drop", "2026-11-19T21:15:00Z", P)
    assert victim not in {m["mint"] for m in out["members"]}
    assert len(out["members"]) == 9
    assert sum(m["weight_bps"] for m in out["members"]) == 10_000
    assert [m["rank"] for m in out["members"]] == sorted(m["rank"] for m in out["members"])
    assert out["emergency"][-1] == {
        "at": "2026-11-19T21:15:00Z",
        "mint": victim,
        "reason": "liquidity_drop",
    }
    assert len(BASE["members"]) == 10  # input not mutated


def test_repeat_and_unknown_removals_are_no_ops() -> None:
    victim = BASE["members"][0]["mint"]
    once = apply_emergency(BASE, victim, "rug_flag", "t1", P)
    twice = apply_emergency(once, victim, "rug_flag", "t2", P)
    assert canonical_json(once) == canonical_json(twice)
    assert canonical_json(apply_emergency(BASE, mint(999), "rug_flag", "t", P)) == canonical_json(
        BASE
    )


def test_reason_required() -> None:
    with pytest.raises(ValueError):
        apply_emergency(BASE, BASE["members"][0]["mint"], "", "t", P)
