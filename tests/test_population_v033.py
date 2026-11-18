"""#84 step 3: the population runs on the real engine and its outputs are sane."""

from __future__ import annotations

from engine.params import CoinParams
from sim import outputs_v033 as out
from sim.population_v033 import FARMER_MIN_GAIN, _farmer_exit_day, simulate


def test_same_seed_same_payouts_and_conservation() -> None:
    a, b = simulate(3, days=12), simulate(3, days=12)
    assert [r.payouts for r in a.results] == [r.payouts for r in b.results]
    for r in a.results:
        assert sum(r.payouts.values()) <= r.pot  # never pays more than the pot


def test_probe_rates_follow_t_start_and_curve() -> None:
    rates = out.rate_by_holding(simulate(1, days=12))
    assert rates[1] == 0  # 1h holds never reach T_START = 1h
    assert rates[4] > 0  # 4h holds already earn (D27)
    assert 0 < rates[4] < rates[12] < rates[24] < rates[72] < rates[168]


def test_small_holder_is_paid_and_entered_in_draws() -> None:
    s = out.small_holder(simulate(2, days=10), draw_samples=200)
    assert s["share"] > 0 and s["days_to_first_payout"] < 10
    assert all(0 < s[f"draw_odds_n{n}"] <= 1 for n, _ in out.DRAWS)


def test_farmer_exit_day_by_curve() -> None:
    assert FARMER_MIN_GAIN > 1
    assert (
        _farmer_exit_day(CoinParams()) == 30
    )  # flat from 4h (D27): no gain from waiting past day 30


def test_gini_and_percentile() -> None:
    assert out.gini([1, 1, 1, 1]) == 0 and out.gini([0, 0, 0, 4]) == 0.75
    assert out.percentile([1, 2, 3, 4], 0.5) == 3 and out.percentile([], 0.5) == 0
