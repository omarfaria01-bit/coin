"""#189 part 2: the four attack classes against the CURRENT index/params.json and D39 draw rules.

Offline, deterministic. Reuses ``reports/index_redteam_replay.py`` metrics (no second harness).
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
    MIN_GROUPS_DEFAULT,
    draw_weights,
    plan_hourly_draw,
)
from index.filters import first_failed_filter  # noqa: E402
from index.select import weights_bps  # noqa: E402
from sim.index_attacks import (  # noqa: E402
    best_sandwich,
    max_mc_for_liquidity,
    min_fee_burn_sol,
    min_liquidity_usd,
    sybil_wallet_cost_sol,
)

P = rt.PARAMS
S = 10**15  # total supply in base units


# ---- 1. cheap top-10 slot: the floor is F2 $50k pool, F11 caps MC at 100x liquidity ----------


def test_cheap_slot_cost_floor_from_params() -> None:
    assert min_liquidity_usd(1_000_000.0, P) == 50_000.0  # F2 binds
    assert min_liquidity_usd(50_000_000.0, P) == 500_000.0  # F11 binds
    assert max_mc_for_liquidity(50_000.0, P) == 5_000_000.0


@settings(max_examples=60, deadline=None)
@given(st.floats(10_000, 5e7), st.floats(1.01, 20))
def test_mc_inflation_above_f11_is_blocked(liq: float, mult: float) -> None:
    liq = max(liq, 50_000.0)
    m_ok = rt.base(
        rt.mint(30),
        "CHEAP",
        "GTA 6 Cheap",
        liquidity_usd=liq,
        mc_usd=max_mc_for_liquidity(liq, P) * 0.999,  # float margin under the exact 100x bound
    )
    m_bad = rt.base(
        rt.mint(30),
        "CHEAP",
        "GTA 6 Cheap",
        liquidity_usd=liq,
        mc_usd=max_mc_for_liquidity(liq, P) * mult,
    )
    assert first_failed_filter(m_ok, P) is None
    assert first_failed_filter(m_bad, P) == "F11"


def test_cheap_slot_still_works_at_the_ratio_bound() -> None:
    # Still works: a $50k pool buys a $5M MC slot. Stopped only by F2 ($50k) and F11 (100x).
    m = rt.base(rt.mint(31), "THIN", "GTA 6 Thin", liquidity_usd=50_000.0, mc_usd=5_000_000.0)
    assert first_failed_filter(m, P) is None


# ---- 2. wash volume: F10 is volume > 0, weights use raw volume at 50% (cap 25%) --------------


def test_wash_volume_buys_weight_but_the_25pct_cap_bounds_it() -> None:
    ms = [f"m{i}" for i in range(10)]
    honest = {m: (1_000_000.0, 100_000.0) for m in ms}
    base = weights_bps(ms, {m: 0.0 for m in ms}, P, honest)
    washed = dict(honest, m0=(1_000_000.0, 100_000_000.0))  # 1000x wash volume on one coin
    w = weights_bps(ms, {m: 0.0 for m in ms}, P, washed)
    assert w["m0"] > base["m0"] and w["m0"] <= 2500
    assert sum(w.values()) == 10_000


@settings(max_examples=60, deadline=None)
@given(st.floats(0, 1e12))
def test_wash_volume_never_exceeds_cap(vol: float) -> None:
    ms = [f"m{i}" for i in range(10)]
    inputs = {m: (1_000_000.0, 100_000.0) for m in ms} | {"m0": (1_000_000.0, vol + 1.0)}
    w = weights_bps(ms, {m: 0.0 for m in ms}, P, inputs)
    assert w["m0"] <= 2500 and sum(w.values()) == 10_000


def test_wash_cost_to_pass_f4() -> None:
    # F4 8 SOL of fees at 1/400 needs 3,200 SOL of DexScreener volume; it is turnover, not spend.
    assert min_fee_burn_sol(P) == 3_200


# ---- 3. sybil traders: F9 needs 50 window wallets of any size --------------------------------


def test_f9_49_wallets_fail_50_pass() -> None:
    m49 = rt.base(rt.mint(32), "S49", "GTA 6 S", unique_traders=49)
    m50 = rt.base(rt.mint(32), "S50", "GTA 6 S", unique_traders=50)
    assert first_failed_filter(m49, P) == "F9"
    assert first_failed_filter(m50, P) is None


def test_f9_sybil_cost_is_50_dust_wallets() -> None:
    # Still works. Cost = 50 wallets x ~0.003 SOL rent+fee dust = 0.15 SOL (assumption, offline).
    assert sybil_wallet_cost_sol(P, Fraction(3, 1000)) == Fraction(15, 100)


# ---- 4. basket sandwich around the hourly prize buy, 3% slippage -----------------------------

SOL = 10**9


def test_sandwich_profit_is_bounded_by_the_slippage_cap() -> None:
    v = 10 * SOL // 100  # 0.1 SOL prize buy
    r = best_sandwich(v, 500 * SOL, 10**15)
    assert r.victim_out >= r.victim_min_out
    assert r.profit <= v * 300 // 10_000  # never more than 3% of the buy


def test_sandwich_gets_cheap_in_thin_pools_and_dies_in_deep_pools() -> None:
    v = SOL // 10
    thin = best_sandwich(v, 10 * SOL, 10**15)
    deep = best_sandwich(v, 5_000 * SOL, 10**15)
    assert thin.profit >= deep.profit
    assert deep.profit <= 0 or deep.profit < v // 1000  # < 0.1% of the buy


@settings(max_examples=80, deadline=None)
@given(st.integers(10**6, 10 * SOL), st.integers(50 * SOL, 10**5 * SOL), st.integers(0, 1000))
def test_sandwich_property_victim_clears_and_profit_le_cap(v: int, rs: int, slip: int) -> None:
    r = best_sandwich(v, rs, 10**15, slippage_bps=slip)
    assert r.victim_out >= r.victim_min_out
    assert r.profit <= v * slip // 10_000 * 102 // 100 + 16  # ~slip x buy, +2% curve, +floor


# ---- 5. D39 draw: linear odds, supply cap, min holding, group gate, rollover -----------------


def _groups(n: int, bal: int) -> tuple[dict, dict]:
    return {f"g{i}": bal for i in range(n)}, {f"g{i}": bal for i in range(n)}


def _plan(scores: dict, bal: dict, pot: int = 10**9):
    return plan_hourly_draw(
        scores,
        pot,
        (10_000,),
        balances=bal,
        total_supply=S,
        genesis_hash=b"g" * 32,
        mint=b"m" * 32,
        draw_index=1,
        snapshot_hash=b"s" * 32,
        rho=b"r" * 32,
    )


def test_fewer_than_100_groups_rolls_over() -> None:
    sc, bal = _groups(MIN_GROUPS_DEFAULT - 1, S // 200)
    plan = _plan(sc, bal)
    assert not plan.drawn and plan.reason == "too_few_groups" and plan.rollover == 10**9


def test_dust_sybil_below_min_holding_is_not_eligible() -> None:
    sc, bal = _groups(MIN_GROUPS_DEFAULT + 20, S // 200)
    for i in range(2000):  # 2000 dust wallets below 0.01% of supply
        sc[f"d{i}"] = 10**3
        bal[f"d{i}"] = S // 100_000
    w = draw_weights(sc, bal, S)
    assert not any(k.startswith("d") for k in w)


@settings(max_examples=40, deadline=None)
@given(st.integers(1, 40))
def test_splitting_across_unlinked_wallets_never_raises_odds(n: int) -> None:
    sc, bal = _groups(300, S // 400)
    one = draw_weights(sc | {"a": 3 * S // 100}, bal | {"a": 3 * S // 100}, S)
    piece = 3 * S // 100 // n
    sc2 = sc | {f"a{i}": piece for i in range(n)}
    bal2 = bal | {f"a{i}": piece for i in range(n)}
    split = draw_weights(sc2, bal2, S)
    odds_one = Fraction(one["a"], sum(one.values()))
    odds_split = Fraction(sum(split.get(f"a{i}", 0) for i in range(n)), sum(split.values()))
    assert odds_split <= odds_one + Fraction(1, 10**9)


def test_supply_cap_whale_counts_at_most_5pct() -> None:
    sc, bal = _groups(300, S // 400)
    sc["whale"], bal["whale"] = 50 * S // 100, 50 * S // 100  # 50% of supply
    w = draw_weights(sc, bal, S)
    assert Fraction(w["whale"], sum(w.values())) <= Fraction(1, 20)
