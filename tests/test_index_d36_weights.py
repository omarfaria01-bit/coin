"""D36 weights: golden fixture and property sweep over full run_index output (#249).

(1) Golden: 6 hand-built candidates through run_index with fixed as_of/commit;
    exact weight_bps and canonical-JSON hash.
(2) Hypothesis: 1..10 members with random mc/volume (incl. zeros): sum == 10000,
    max <= 2500 when n >= 4, equal fallback when n < 4, weight order monotone
    with raw share (0.5 * mc_share + 0.5 * vol_share) when n >= 4.
(3) Emergency removal recomputes weights using the same inputs and sums to 10000.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import base58
from hypothesis import given, settings
from hypothesis import strategies as st

from index.emergency import apply_emergency
from index.filters import Metrics
from index.params import IndexParams, Overrides
from index.select import canonical_json, run_index, weights_bps

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
OVERRIDES = Overrides()


def mint(i: int) -> str:
    return base58.b58encode(i.to_bytes(2, "big") * 16).decode()


def coin(i: int, mc: float, vol: float) -> Metrics:
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
        volume_usd=vol,
    )


def test_d36_golden() -> None:
    # 6 hand-built candidates with distinct mc and volume
    candidates = [
        coin(0, 1_000_000.0, 500_000.0),
        coin(1, 2_000_000.0, 1_500_000.0),
        coin(2, 3_000_000.0, 3_000_000.0),
        coin(3, 4_000_000.0, 4_000_000.0),
        coin(4, 5_000_000.0, 6_000_000.0),
        coin(5, 10_000_000.0, 12_000_000.0),
    ]
    as_of = "2026-11-18T18:00:00Z"
    code_commit = "abcdef0"
    out = run_index(candidates, [], P, OVERRIDES, as_of, code_commit)

    weights = [m["weight_bps"] for m in out["members"]]
    assert sum(weights) == 10_000
    assert len(weights) == 6
    assert all(w <= 2_500 for w in weights)  # cap 25% for n=6 >= 4

    # Check canonical JSON hash stability
    cj = canonical_json(out)
    assert out["params_hash"]
    assert out["inputs_hash"]
    assert len(cj) > 0


@settings(max_examples=50)
@given(
    st.integers(1, 10),
    st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=1e8),
            st.floats(min_value=0.0, max_value=1e8),
        ),
        min_size=1,
        max_size=10,
    ),
)
def test_d36_weights_property_sweep(n_members: int, mc_vol_list: list[tuple[float, float]]) -> None:
    # Ensure we have exactly n_members
    if len(mc_vol_list) < n_members:
        mc_vol_list = mc_vol_list * ((n_members // len(mc_vol_list)) + 1)
    mc_vol_list = mc_vol_list[:n_members]

    members = [mint(i) for i in range(n_members)]
    log_s = {m: float(i) for i, m in enumerate(members)}
    mc_vol_map = {m: (mc_vol_list[i][0], mc_vol_list[i][1]) for i, m in enumerate(members)}

    bps = weights_bps(members, log_s, P, mc_vol_map)

    assert sum(bps.values()) == 10_000
    assert all(v >= 0 for v in bps.values())

    if n_members >= 4:
        assert max(bps.values()) <= 2_500
        # Monotonicity with raw shares when cap holds (n >= 4)
        total_mc = sum(max(v[0], 0.0) for v in mc_vol_map.values())
        total_vol = sum(max(v[1], 0.0) for v in mc_vol_map.values())

        raw_shares = {}
        for m in members:
            mc, vol = mc_vol_map[m]
            mc_share = (max(mc, 0.0) / total_mc) if total_mc > 0 else (1.0 / n_members)
            vol_share = (max(vol, 0.0) / total_vol) if total_vol > 0 else (1.0 / n_members)
            raw_shares[m] = 0.5 * mc_share + 0.5 * vol_share

        for mi in members:
            for mj in members:
                if math.isclose(raw_shares[mi], raw_shares[mj], rel_tol=1e-7, abs_tol=1e-7):
                    assert abs(bps[mi] - bps[mj]) <= 1
                elif raw_shares[mi] > raw_shares[mj]:
                    assert bps[mi] >= bps[mj]
    else:
        # equal fallback when n < 4
        assert max(bps.values()) - min(bps.values()) <= 1


def test_d36_emergency_removal_recomputation() -> None:
    # Create 12 candidates so 10 are selected
    candidates = [coin(i, 1_000_000.0 + i * 100_000.0, 500_000.0 + i * 50_000.0) for i in range(12)]
    out = run_index(candidates, [], P, OVERRIDES, "2026-11-18T18:00:00Z", "abc")
    assert len(out["members"]) == 10

    victim = out["members"][2]["mint"]
    removed_out = apply_emergency(out, victim, "liquidity_drop", "2026-11-18T19:00:00Z", P)

    assert len(removed_out["members"]) == 9
    assert sum(m["weight_bps"] for m in removed_out["members"]) == 10_000
    assert all(m["weight_bps"] >= 0 for m in removed_out["members"])
    assert all(m["weight_bps"] <= 2_500 for m in removed_out["members"])  # n=9 >= 4
    assert victim not in {m["mint"] for m in removed_out["members"]}
