"""#189: red-team attack classes replayed against the hourly schedule (offline, deterministic).

Reuses the synthetic metrics from ``reports/index_redteam_replay.py`` (no second harness).
Each test asserts an outcome: blocked, or "still works" with a bound.
"""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reports"))

import index_redteam_replay as rt  # noqa: E402

from engine.hourly_draw import (  # noqa: E402
    CAP_DEFAULT,
    MIN_POT_LAMPORTS_DEFAULT,
    cap_weights,
    plan_hourly_draw,
)
from engine.params import HoldParams  # noqa: E402
from engine.scoring import h_of_age  # noqa: E402
from index.filters import first_failed_filter  # noqa: E402
from index.select import run_index, select_members, weights_bps  # noqa: E402

P = rt.PARAMS
HOLD = HoldParams()
KNOTS = tuple((a, Fraction(h)) for a, h in HOLD.knots)
T_START = HOLD.t_start_seconds


def _hourly(metrics: list, prev: list[str], hour: int) -> dict:
    return run_index(metrics, prev, P, rt.OVERRIDES, f"2026-11-18T{hour:02d}:00:00Z", "hourly")


# ---- 1. cheap top-10 (low float / thin liquidity), #167 -------------------------------------


def test_lowfloat_blocked_at_every_hourly_rebalance() -> None:
    assert first_failed_filter(rt.LOWFLOAT, P) == "F11"
    prev: list[str] = []
    for hour in range(6):
        out = _hourly([rt.LEGIT, rt.LOWFLOAT, *rt.FILLERS], prev, hour)
        tickers = [m["ticker"] for m in out["members"]]
        assert "FLOAT" not in tickers
        prev = [m["mint"] for m in out["members"]]


# ---- 2. wash volume / 3. sybil traders, #170 -------------------------------------------------


def test_wash_volume_and_fake_traders_blocked_every_hour() -> None:
    assert first_failed_filter(rt.SYBIL, P) == "F9"
    prev: list[str] = []
    for hour in range(6):
        out = _hourly([rt.LEGIT, rt.SYBIL, *rt.FILLERS], prev, hour)
        assert "SYBIL" not in [m["ticker"] for m in out["members"]]
        prev = [m["mint"] for m in out["members"]]


def test_d38_dust_sybil_is_an_accepted_risk() -> None:
    # D38 (calibrated on kiwi's reference coins): F9 counts distinct window wallets of any size,
    # so 250 dust wallets (each < 0.05 SOL) now pass F9. Said plainly in DECISIONS.md D38.
    dust = rt.base(rt.mint(22), "DUST", "GTA 6 Dust", independent_traders=0, unique_traders=250)
    assert first_failed_filter(dust, P) is None


def test_round_trip_wash_is_not_filtered_after_d35() -> None:
    # kiwi 18 Nov (D35): raw volume as-is, F10 is only volume > 0. Wash volume is an accepted
    # risk; F9 (200 independent traders) is what still has to be faked.
    wash = rt.base(rt.mint(20), "WASH", "GTA 6 Wash", roundtrip_share=0.9)
    assert first_failed_filter(wash, P) is None
    few = rt.base(rt.mint(21), "WASH2", "GTA 6 Wash", roundtrip_share=0.9, unique_traders=5)
    assert first_failed_filter(few, P) == "F9"


# ---- 4. hysteresis: one hour of rank noise must not churn the basket -------------------------


def test_hysteresis_keeps_member_until_exit_rank() -> None:
    mp = P.membership
    ranked = [f"m{i}" for i in range(1, 21)]
    prev = ranked[: mp.size]
    # incumbent drops to just inside exit_rank: kept
    shuffled = [r for r in ranked if r != "m10"]
    shuffled.insert(mp.exit_rank - 1, "m10")
    assert "m10" in select_members(shuffled, prev, P)
    # incumbent drops beyond exit_rank: removed
    shuffled = [r for r in ranked if r != "m10"]
    shuffled.insert(mp.exit_rank + 1, "m10")
    assert "m10" not in select_members(shuffled, prev, P)


def test_newcomer_needs_enter_rank_to_displace() -> None:
    mp = P.membership
    ranked = [f"m{i}" for i in range(1, 21)]
    prev = ranked[: mp.size]
    # outsider at rank enter_rank+1 does not enter while incumbents stay inside exit_rank
    out = [r for r in ranked if r != "m15"]
    out.insert(mp.enter_rank, "m15")
    assert "m15" not in select_members(out, prev, P)


@settings(max_examples=60, deadline=None)
@given(st.permutations(list(range(15))))
def test_select_members_size_and_membership_props(order: list[int]) -> None:
    ranked = [f"m{i}" for i in order]
    prev = [f"m{i}" for i in range(P.membership.size)]
    members = select_members(ranked, prev, P)
    assert len(members) == P.membership.size
    assert len(set(members)) == len(members)
    pos = {m: i + 1 for i, m in enumerate(ranked)}
    for m in members:
        assert pos[m] <= P.membership.exit_rank or m not in prev


# ---- 5. 1h-wait multiplier curve (D27): no score before T_START, monotone to the max --------


def test_curve_zero_before_one_hour_and_five_x_at_four_hours() -> None:
    assert T_START == 3_600
    assert h_of_age(0, KNOTS, T_START) == 0
    assert h_of_age(T_START - 1, KNOTS, T_START) == 0
    assert h_of_age(T_START, KNOTS, T_START) == 1
    assert h_of_age(4 * 3_600, KNOTS, T_START) == 5
    assert h_of_age(40 * 3_600, KNOTS, T_START) == 5


@settings(max_examples=100, deadline=None)
@given(st.integers(0, 10 * 3_600), st.integers(0, 3_600))
def test_curve_monotone_and_bounded(age: int, delta: int) -> None:
    a, b = h_of_age(age, KNOTS, T_START), h_of_age(age + delta, KNOTS, T_START)
    assert 0 <= a <= b <= 5


@settings(max_examples=100, deadline=None)
@given(st.integers(1, 3_599))
def test_in_and_out_inside_first_hour_scores_nothing(held: int) -> None:
    """Flash-buy / sell inside the 1h wait earns zero (anti sniping and churn)."""
    assert h_of_age(held, KNOTS, T_START) == 0


# ---- 6. hourly draw: threshold, rollover, 5% cap, sybil split ------------------------------


def _plan(scores: dict, pot: int, idx: int = 1):
    return plan_hourly_draw(
        scores,
        pot,
        (10_000,),
        genesis_hash=b"g" * 32,
        mint=b"m" * 32,
        draw_index=idx,
        snapshot_hash=b"s" * 32,
        rho=b"r" * 32,
        balances=dict(scores),
        total_supply=10**18,
        min_holding_share=Fraction(1, 10**18),
    )


def test_below_min_pot_rolls_over_and_conserves() -> None:
    plan = _plan({f"c{i}": 100 for i in range(30)}, MIN_POT_LAMPORTS_DEFAULT - 1)
    assert not plan.drawn and plan.reason == "below_min_pot"
    assert plan.rollover == MIN_POT_LAMPORTS_DEFAULT - 1 and plan.prizes == {}


@settings(max_examples=60, deadline=None)
@given(
    st.integers(MIN_POT_LAMPORTS_DEFAULT, 10**12),
    st.integers(1, 10**6),
    st.integers(0, 10**6),
)
def test_draw_conserves_pot(pot: int, whale_score: int, idx: int) -> None:
    scores = {f"c{i}": 100 for i in range(120)} | {"whale": whale_score}
    plan = _plan(scores, pot, idx)
    assert sum(plan.prizes.values()) + plan.rollover == pot


def test_splitting_one_score_across_wallets_does_not_help_when_merged() -> None:
    """Linked wallets are merged into one cluster upstream; the cap bounds a cluster at 5%."""
    from engine.hourly_draw import CAP_DEFAULT, cap_weights

    weights = cap_weights({"whale": 10**9, **{f"c{i}": 10 for i in range(40)}})
    total = sum(weights.values())
    assert Fraction(weights["whale"], total) <= CAP_DEFAULT + Fraction(1, 1000)


def test_basket_sandwich_weights_and_draw_caps() -> None:
    """Prize-basket sandwiching is bounded by weights.cap_pct and the 5% draw odds cap."""
    mints = [rt.mint(i) for i in range(1, 31)]
    log_scores = {m: 5.0 for m in mints}
    log_scores[mints[0]] = 20.0
    mc_volume = {m: (2_000_000.0, 300_000.0) for m in mints}
    mc_volume[mints[0]] = (50_000_000.0, 10_000_000.0)
    bps = weights_bps(mints, log_scores, rt.PARAMS, mc_volume)
    assert max(bps.values()) <= int(rt.PARAMS.weights.cap_pct * 100)

    scores = {m: 1000 for m in mints}
    scores[mints[0]] = 10_000_000
    draw_capped = cap_weights({m: score for m, score in scores.items()}, CAP_DEFAULT)
    total_draw_weight = sum(draw_capped.values())
    max_draw_share = Fraction(max(draw_capped.values()), total_draw_weight)
    assert max_draw_share <= CAP_DEFAULT + Fraction(1, 1000)
