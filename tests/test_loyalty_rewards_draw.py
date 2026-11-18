"""D43: loyalty breakpoints, daily dust carry, single SOL prize behind a disabled flag."""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.fees import route_v033
from engine.hourly_draw import DRAW_COMING_SOON, SOL_PRIZE_MIN_LAMPORTS, plan_sol_prize
from engine.loyalty import DAY, HOUR, T_CAP, loyalty_multiplier, loyalty_scores, loyalty_weight
from engine.params import FeeParams
from engine.rewards import (
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    allocate_holder_rewards,
    settle_daily_rewards,
)
from engine.scoring import h_of_age
from index.params import IndexParams

ROOT = Path(__file__).resolve().parents[1]
B = b"\x11" * 32
_BREAKS = (
    (0, 0),
    (HOUR - 1, 0),
    (HOUR, 1),
    (90 * 60, 1),  # 1h30, still 1x
    (75 * 60, 1),  # 1h15, inside the flat 1x span
    (105 * 60, Fraction(3, 2)),
    (2 * HOUR, 2),
    (150 * 60, 3),
    (3 * HOUR, 4),
    (4 * HOUR, 5),
    (T_CAP, 10),
    (T_CAP + DAY, 10),
)


@pytest.mark.parametrize(("age", "height"), _BREAKS)
def test_breakpoints(age: int, height: int | Fraction) -> None:
    assert loyalty_multiplier(age) == height


def test_knot_span_matches_the_epoch_curve_and_then_logs() -> None:
    for age in range(0, 4 * HOUR + 1, 30):
        assert loyalty_multiplier(age) == h_of_age(age)
    # 1h37m30s is halfway from 1x to 1.5x; 3h30 is halfway from 4x to 5x.
    assert loyalty_multiplier(97 * 60 + 30) == Fraction(5, 4)
    assert loyalty_multiplier(210 * 60) == Fraction(9, 2)
    # Geometric midpoint of 4h and 30d is 7.5x on a log curve. A linear ramp in
    # time is still about 5.3x there, because that midpoint is early.
    mid = math.isqrt(4 * HOUR * T_CAP)
    got = loyalty_multiplier(mid)
    assert abs(got - Fraction(15, 2)) < Fraction(1, 100_000)
    linear = Fraction(5) + 5 * Fraction(mid - 4 * HOUR, T_CAP - 4 * HOUR)
    assert got > linear + 2
    assert Fraction(5) < loyalty_multiplier(4 * HOUR + 1) < got < loyalty_multiplier(T_CAP - 1) < 10


@given(st.integers(0, 60 * DAY), st.integers(0, 60 * DAY))
@settings(max_examples=40, deadline=None)
def test_monotone_and_capped(a: int, b: int) -> None:
    lo, hi = (a, b) if a <= b else (b, a)
    h_lo, h_hi = loyalty_multiplier(lo), loyalty_multiplier(hi)
    assert Fraction(0) <= h_lo <= h_hi <= Fraction(10)


def test_rewards_and_draw_share_the_multiplier() -> None:
    bal = {"early": 100, "hour": 100, "two": 100}
    held = {"early": HOUR - 1, "hour": HOUR, "two": 2 * HOUR}
    scores = loyalty_scores(bal, held)
    assert scores["early"] == 0
    assert scores["hour"] == loyalty_weight(100, HOUR) == 100
    assert scores["two"] == 200  # 2x
    # 1 : 2, so a budget of 3000 lands 1000 / 2000. The sub-hour wallet gets nothing.
    paid = allocate_holder_rewards(3000, bal, held)
    assert paid == {"early": 0, "hour": 1000, "two": 2000}
    assert sum(paid.values()) == 3000


def test_daily_pay_carries_dust_under_token_account_rent() -> None:
    rent = TOKEN_ACCOUNT_RENT_LAMPORTS
    dust = settle_daily_rewards({}, {"w": 50}, {"w": rent - 1}, day_index=1)
    assert dust.paid == {} and dust.carry == {"w": 50}
    # A configured floor under the rent cannot open an account for dust.
    still = settle_daily_rewards(
        dust.carry, {}, {"w": rent - 1}, day_index=2, min_payout_lamports=1
    )
    assert still.paid == {} and still.carry == {"w": 50}
    cleared = settle_daily_rewards(
        {"w": 40}, {"w": 10}, {"w": rent}, day_index=3, last_paid_day=still.last_paid_day
    )
    assert cleared.paid == {"w": 50} and cleared.carry == {}
    # Same day does not pay again; the new credit carries.
    again = settle_daily_rewards(
        {}, {"w": 7}, {"w": rent * 2}, day_index=3, last_paid_day=cleared.last_paid_day
    )
    assert again.paid == {} and again.carry == {"w": 7}
    nxt = settle_daily_rewards(
        again.carry, {}, {"w": rent}, day_index=4, last_paid_day=again.last_paid_day
    )
    assert nxt.paid == {"w": 7} and nxt.carry == {}


def test_fee_split_stays_70_30_zero_team() -> None:
    assert route_v033(1_000, FeeParams()) == {
        "dev": 0,
        "holder_pot": 700,
        "draw_pot": 300,
        "buyback_burn": 0,
    }
    p = IndexParams.model_validate(json.loads((ROOT / "index/params.json").read_text()))
    assert (p.payout.holder_rewards, p.payout.draw_pot, p.payout.team) == ("67/100", "7/25", 0)
    assert p.payout.pay_in == "basket" and p.payout.holder_reward_hours == 24
    assert p.payout.min_reward_lamports == TOKEN_ACCOUNT_RENT_LAMPORTS
    assert p.payout.draw_enabled is False and p.payout.draw_status == "coming_soon"
    assert p.payout.draw_winners == 1
    assert p.payout.draw_min_pot_lamports == SOL_PRIZE_MIN_LAMPORTS


def _draw(pot: int, enabled: bool, n: int = 2):
    bal = {f"c{i}": 10**15 for i in range(n)}
    held = {f"c{i}": HOUR * (i + 1) for i in range(n)}
    return plan_sol_prize(
        bal,
        held,
        pot,
        total_supply=10**18,
        genesis_hash=B,
        mint=B,
        draw_index=1,
        snapshot_hash=B,
        rho=B,
        enabled=enabled,
        min_groups=1,
        cap=Fraction(1),
    )


def test_draw_is_one_sol_prize_and_stays_coming_soon() -> None:
    off = _draw(10**9, enabled=False)
    assert not off.drawn and off.reason == DRAW_COMING_SOON and off.rollover == 10**9
    small = _draw(SOL_PRIZE_MIN_LAMPORTS - 1, enabled=True)
    assert not small.drawn and small.reason == "below_min_pot"
    assert small.rollover == SOL_PRIZE_MIN_LAMPORTS - 1 and small.prizes == {}
    live = _draw(SOL_PRIZE_MIN_LAMPORTS, enabled=True)
    assert live.drawn and live.reason == "ok" and len(live.winners) == 1
    assert sum(live.prizes.values()) == SOL_PRIZE_MIN_LAMPORTS and live.rollover == 0
    # The 2h holder weighs twice the 1h holder, so it is the heavier ticket.
    scores = loyalty_scores({"c0": 10**15, "c1": 10**15}, {"c0": HOUR, "c1": 2 * HOUR})
    assert scores["c1"] == 2 * scores["c0"]
