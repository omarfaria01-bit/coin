"""D40 weights (kiwi delegated, 18 Nov 14:20 Rome): w ~ sqrt(MC), cap 18%, floor 5%.

(1) Golden: 6 hand-built candidates through run_index with fixed as_of/commit.
(2) Hypothesis: 1..25 members with random MC (incl. zeros): sum == 10000, every weight in
    [floor, cap] (relaxed to 1/n when infeasible), monotone in MC.
(3) Emergency removal recomputes weights and sums to 10000.
"""

from __future__ import annotations

import hashlib
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
        trading_fees_24h_sol=40.0,
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


def test_d40_golden() -> None:
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
    # Hand-checked: sqrt(MC) for 10/5/4/3/2/1 M = 3162/2236/2000/1732/1414/1000. The top four
    # hit the 18% cap (72%); the last 28% splits 1414:1000 -> 16.40% / 11.60%.
    assert weights == [1_800, 1_800, 1_800, 1_800, 1_640, 1_160]
    assert sum(weights) == 10_000

    # Canonical JSON is byte-stable. The hash includes the embedded params, so it
    # moves when vocabulary or payout fields change. The weight vector above does not.
    cj = canonical_json(out)
    assert cj == canonical_json(run_index(candidates, [], P, OVERRIDES, as_of, code_commit))
    raw = cj if isinstance(cj, bytes) else cj.encode()
    assert hashlib.sha256(raw).hexdigest() == (
        "8092126ad517894f363d7f4850b34557e12c1d259eaeac467ffb5ee19307d8f0"
    )


@settings(max_examples=300, deadline=None)
@given(
    st.integers(1, 25),
    st.lists(st.floats(min_value=0.0, max_value=1e12), min_size=25, max_size=25),
)
def test_d40_weights_property_sweep(n: int, mcs: list[float]) -> None:
    members = [mint(i) for i in range(n)]
    mc = {m: (mcs[i], 0.0) for i, m in enumerate(members)}
    bps = weights_bps(members, dict.fromkeys(members, 0.0), P, mc)
    assert sum(bps.values()) == 10_000
    cap = max(1_800, math.ceil(10_000 / n))  # relaxed to 1/n when 18% can't hold (n <= 5)
    floor = min(500, 10_000 // n)  # relaxed to 1/n when 5% can't hold (n > 20)
    assert all(floor <= v <= cap for v in bps.values()), bps
    for a in members:  # monotone in sqrt(MC): a bigger coin never weighs less (1 bp rounding)
        for b in members:
            if mc[a][0] > mc[b][0]:
                assert bps[a] >= bps[b] - 1
            if mc[a][0] == mc[b][0]:
                assert abs(bps[a] - bps[b]) <= 1


def test_d40_dry_run_shape() -> None:
    """The 18 Nov 12:00Z dry-run market caps give kiwi's expected spread."""
    caps = [14.79e6, 7.51e6, 1.71e6, 1.74e6, 1.64e6, 1.29e6, 0.857e6, 0.454e6, 0.616e6, 0.693e6]
    members = [mint(i) for i in range(10)]
    bps = weights_bps(members, {}, P, {m: (caps[i], 0.0) for i, m in enumerate(members)})
    assert [bps[m] for m in members] == [1800, 1800, 1013, 1022, 992, 880, 718, 522, 608, 645]


def test_d40_emergency_removal_recomputation() -> None:
    # Create 12 candidates so 10 are selected
    candidates = [coin(i, 1_000_000.0 + i * 100_000.0, 500_000.0 + i * 50_000.0) for i in range(12)]
    out = run_index(candidates, [], P, OVERRIDES, "2026-11-18T18:00:00Z", "abc")
    assert len(out["members"]) == 10

    victim = out["members"][2]["mint"]
    removed_out = apply_emergency(out, victim, "liquidity_drop", "2026-11-18T19:00:00Z", P)

    assert len(removed_out["members"]) == 9
    assert sum(m["weight_bps"] for m in removed_out["members"]) == 10_000
    assert all(m["weight_bps"] >= 0 for m in removed_out["members"])
    assert all(m["weight_bps"] <= 1_800 for m in removed_out["members"])  # n=9: 18% cap holds
    assert victim not in {m["mint"] for m in removed_out["members"]}


def test_d36_zero_raw_free_members_share_budget_equally() -> None:
    """Regression: after capping, free members with zero mc and volume must not divide by zero."""
    members = [mint(i) for i in range(4)]
    log_s = {m: float(i) for i, m in enumerate(members)}
    mcv = {
        members[0]: (0.0, 0.0),
        members[1]: (1.0, 1.0),
        members[2]: (0.0, 0.0),
        members[3]: (1.0, 1.0),
    }
    bps = weights_bps(members, log_s, P, mcv)
    assert sum(bps.values()) == 10_000
    assert bps[members[1]] == bps[members[3]] == 2_500
    assert bps[members[0]] == bps[members[2]] == 2_500
