"""index/select.py: buffer membership, emergency, weights, prize split, output (§5–§8, #156)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import base58
import pytest
from hypothesis import given
from hypothesis import strategies as st

from index.filters import Metrics
from index.params import IndexParams, Overrides
from index.select import (
    canonical_json,
    emergency_reason,
    run_index,
    select_members,
    split_prize,
    weights_bps,
)

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
EQUAL = P.model_copy(update={"weights": P.weights.model_copy(update={"mode": "equal"})})
CAPPED = P.model_copy(
    update={"weights": P.weights.model_copy(update={"mode": "score_capped", "cap_pct": 20})}
)


def mint(i: int) -> str:
    return base58.b58encode(i.to_bytes(2, "big") * 16).decode()


def coin(i: int, mc: float) -> Metrics:
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
        volume_usd=mc,
    )


# ------------------------------------------------------------------ §5


def test_first_rebalance_is_top_ten() -> None:
    ranked = [mint(i) for i in range(15)]
    assert select_members(ranked, [], P) == ranked[:10]


def test_member_kept_until_rank_twelve_and_newcomer_needs_top_eight() -> None:
    ranked = [mint(i) for i in range(15)]
    prev = ranked[:7] + [ranked[11]] + [ranked[12], ranked[13]]  # ranks 1–7, 12, 13, 14
    out = select_members(ranked, prev, P)
    assert ranked[7] in out  # newcomer at rank 8 enters
    assert ranked[11] in out  # member at rank 12 stays
    assert ranked[12] not in out and ranked[13] not in out  # members beyond 12 leave
    assert len(out) == 10  # filled with ranks 9 and 10


@given(st.integers(0, 30), st.sets(st.integers(0, 40), max_size=15))
def test_buffer_invariants(n: int, prev_idx: set[int]) -> None:
    ranked = [mint(i) for i in range(n)]
    prev = [mint(i) for i in prev_idx]
    out = select_members(ranked, prev, P)
    pos = {m: i + 1 for i, m in enumerate(ranked)}
    assert len(out) == min(10, n) and len(set(out)) == len(out)
    assert out == sorted(out, key=lambda m: pos[m])
    assert all(m in out for m in ranked[:8])  # top 8 always in
    e = [m for m in ranked if pos[m] <= 8 or (m in set(prev) and pos[m] <= 12)]
    for m in out:
        if pos[m] > 12 or (m not in set(prev) and pos[m] > 8):
            assert len(e) < 10  # only the fill step adds these


def test_emergency_reasons() -> None:
    assert emergency_reason(50.0, 100.0, True, True, False, P) == "liquidity_drop"
    assert emergency_reason(51.0, 100.0, True, True, False, P) is None
    assert emergency_reason(100.0, 100.0, True, False, False, P) == "authority_enabled"
    assert emergency_reason(None, None, None, None, True, P) == "rug_flag"


def test_liquidity_drop_needs_two_samples() -> None:
    args = (50.0, 100.0, True, True, False, P)
    assert emergency_reason(*args, earlier=(100.0, 100.0)) is None  # single print
    assert emergency_reason(*args, earlier=(None, None)) is None  # no earlier data
    assert emergency_reason(*args, earlier=(60.0, 100.0)) is None  # earlier drop only 40%
    assert emergency_reason(*args, earlier=(45.0, 100.0)) == "liquidity_drop"
    # authority/rug stay immediate
    assert emergency_reason(100.0, 100.0, True, False, False, P, earlier=(1.0, 1.0)) == (
        "authority_enabled"
    )


# ------------------------------------------------------------------ §6–§7


@given(st.integers(1, 15), st.lists(st.floats(-5, 5), min_size=15, max_size=15))
def test_weights_sum_and_cap(n: int, scores: list[float]) -> None:
    members = [mint(i) for i in range(n)]
    log_s = {m: round(scores[i], 12) for i, m in enumerate(members)}
    for params in (EQUAL, CAPPED):
        bps = weights_bps(members, log_s, params)
        assert sum(bps.values()) == 10_000 and all(v >= 0 for v in bps.values())
        if params is CAPPED and n >= 5:
            assert max(bps.values()) <= 2_000
        if params is EQUAL or n < 5:
            assert max(bps.values()) - min(bps.values()) <= 1  # equal (or fallback)


@given(st.integers(0, 10**15), st.integers(1, 10))
def test_prize_split_conserves_lamports(lamports: int, n: int) -> None:
    members = [mint(i) for i in range(n)]
    bps = weights_bps(members, dict.fromkeys(members, 0.0), EQUAL)
    parts = split_prize(lamports, members, bps)
    assert sum(parts.values()) == lamports and all(v >= 0 for v in parts.values())
    floors = {m: lamports * bps[m] // 10_000 for m in members}
    assert all(parts[m] == floors[m] for m in members[1:])  # only rank 1 gets the remainder
    assert parts[members[0]] == floors[members[0]] + lamports - sum(floors.values())


# ------------------------------------------------------------------ §8


def test_run_index_is_deterministic_and_complete() -> None:
    coins = [coin(i, 1_000_000.0 + i * 10_000) for i in range(14)]
    coins.append(replace(coin(50, 2e6), top10_pct=40.0))  # fails F3
    coins.append(replace(coin(51, 2e6), name="Dog", ticker="DOG"))  # no keyword
    kw = {"params": P, "overrides": Overrides(), "as_of": "2026-11-19T18:00:00Z"}
    a = run_index(coins, [], code_commit="abc", **kw)  # type: ignore[arg-type]
    b = run_index(list(reversed(coins)), [], code_commit="abc", **kw)  # type: ignore[arg-type]
    assert canonical_json(a) == canonical_json(b)
    assert [m["rank"] for m in a["members"]] == list(range(1, 11))
    assert a["members"][0]["ticker"] == "GTA13"  # highest MC
    assert sum(m["weight_bps"] for m in a["members"]) == 10_000
    reasons = {e["ticker"]: e["reason"] for e in a["excluded"]}
    assert reasons == {"GTA50": "F3"}
    assert a["dry_run"] is False and a["changes"]["exited"] == []


def test_exit_reasons_reported() -> None:
    coins = [coin(i, 1_000_000.0 + i * 10_000) for i in range(12)]
    prev = [mint(0), mint(99)]
    coins[0] = replace(coins[0], trading_fees_24h_sol=1.0)  # fails F4 (D38 measure)
    out = run_index(coins, prev, P, Overrides(), "2026-11-20T18:00:00Z", "abc")
    exited = {e["mint"]: e["reason"] for e in out["changes"]["exited"]}
    assert exited == {mint(0): "F4", mint(99): "not_measured"}


# ------------------------------------------------------------------ D36 mc_volume_capped


def test_default_weights_mode_is_mc_volume_capped_25() -> None:
    assert P.weights.mode == "mc_volume_capped" and P.weights.cap_pct == 25


def test_mc_volume_weights_example() -> None:
    members = [mint(i) for i in range(5)]
    mcv = {
        members[0]: (400.0, 100.0),
        members[1]: (200.0, 100.0),
        members[2]: (200.0, 100.0),
        members[3]: (100.0, 100.0),
        members[4]: (100.0, 100.0),
    }
    bps = weights_bps(members, dict.fromkeys(members, 0.0), P, mcv)
    # raw: 0.5*mc + 0.5*0.2 -> .4, .3, .3, .2, .2 ... mc shares .4 .2 .2 .1 .1, vol .2 each
    # = .3 .2 .2 .15 .15 (all under the 25% cap except rank 1 at 30%)
    assert sum(bps.values()) == 10_000
    assert bps[members[0]] == 2_500  # capped, excess water-filled to the rest
    assert bps[members[1]] == bps[members[2]] > bps[members[3]] == bps[members[4]]
    assert max(bps.values()) <= 2_500


@given(
    st.integers(1, 12),
    st.lists(st.tuples(st.floats(0, 1e9), st.floats(0, 1e9)), min_size=12, max_size=12),
)
def test_mc_volume_weights_conserve_and_cap(n: int, vals: list[tuple[float, float]]) -> None:
    members = [mint(i) for i in range(n)]
    mcv = {m: vals[i] for i, m in enumerate(members)}
    bps = weights_bps(members, dict.fromkeys(members, 0.0), P, mcv)
    assert sum(bps.values()) == 10_000 and all(v >= 0 for v in bps.values())
    if n >= 4:
        assert max(bps.values()) <= 2_500
    else:
        assert max(bps.values()) - min(bps.values()) <= 1  # equal fallback


def test_mc_volume_requires_inputs() -> None:
    members = [mint(i) for i in range(5)]
    with pytest.raises(ValueError):
        weights_bps(members, dict.fromkeys(members, 0.0), P)
