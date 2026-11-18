"""D28 hourly draw fairness (#225): cap, conservation/floor, sybil-merge invariance, rollover."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.hourly_draw import CAP_DEFAULT, MIN_POT_LAMPORTS_DEFAULT, plan_hourly_draw
from sim.hourly_draw_fairness import (
    GENESIS,
    MIN_HOLDING,
    MINT,
    PRIZE_BPS,
    SMALL_SCORE,
    SNAPSHOT,
    SUPPLY,
    WHALE_SCORE,
    _plan,
    equal_holders,
    merged,
    odds,
    simulate,
    simulate_rollover,
    whale_and_small,
    whale_split_and_small,
)

ROOT = Path(__file__).resolve().parents[1]


def test_whale_odds_are_capped_at_five_percent() -> None:
    shares = odds(merged(whale_and_small())[0])
    assert shares["w00"] == CAP_DEFAULT == Fraction(1, 20)
    assert max(shares.values()) == CAP_DEFAULT and sum(shares.values()) == 1


def test_sybil_split_merges_to_the_same_cluster_and_odds() -> None:
    unsplit, split = whale_and_small(), whale_split_and_small()
    assert merged(unsplit) == merged(split)
    assert odds(merged(unsplit)[0]) == odds(merged(split)[0])
    a = simulate(unsplit, draws=300, seed="merge")
    b = simulate(split, draws=300, seed="merge")
    assert a.outcome_digest == b.outcome_digest
    assert (a.rank1, a.paid, a.rolled, a.violations) == (b.rank1, b.paid, b.rolled, b.violations)


def test_unlinked_splits_escape_the_cap_but_never_beat_proportional() -> None:
    """D39: linear odds — a split can at most recover the whale's proportional share."""
    classes = merged(replace(whale_split_and_small(), links=()))[1]
    scores = merged(replace(whale_split_and_small(), links=()))[0]
    whale = sum(s for c, s in odds(scores).items() if classes[c] == "whale")
    proportional = Fraction(WHALE_SCORE, WHALE_SCORE + 500 * SMALL_SCORE)
    assert whale == Fraction(1, 2) <= proportional  # 10 fragments, each capped at 5%


@given(
    pot=st.integers(min_value=0, max_value=10**12),
    score=st.integers(min_value=1, max_value=10**12),
    other=st.integers(min_value=1, max_value=10**12),
)
@settings(max_examples=60, deadline=None)
def test_every_draw_conserves_in_ints(pot: int, score: int, other: int) -> None:
    kw = {"genesis_hash": GENESIS, "mint": MINT, "snapshot_hash": SNAPSHOT, "rho": GENESIS}
    scores = {"a": score, "b": other} | {f"c{i:03d}": other for i in range(120)}
    plan = plan_hourly_draw(
        scores, pot, PRIZE_BPS, draw_index=0, balances=scores, total_supply=SUPPLY * 10**6,
        min_holding_share=MIN_HOLDING / 10**9, **kw,
    )  # fmt: skip
    assert sum(plan.prizes.values()) + plan.rollover == pot
    assert all(type(v) is int for v in plan.prizes.values())
    assert type(plan.rollover) is int and plan.rollover >= 0
    if pot < MIN_POT_LAMPORTS_DEFAULT:
        assert not plan.drawn and plan.rollover == pot


def test_floor_keeps_the_remainder_in_the_pot() -> None:
    plan = _plan(merged(whale_and_small())[0], 10_000_003, 0, "floor")
    assert len(plan.winners) == 10  # all ten prize ranks paid
    assert (sum(plan.prizes.values()), plan.rollover) == (10_000_001, 2)


def test_rollover_carries_the_whole_pot_for_24_hours() -> None:
    result = simulate_rollover(whale_and_small(), hours=25)
    assert result.cycle[23] == (24, 9_600_000, False, 0, 9_600_000)
    assert result.cycle[24] == (25, 10_000_000, True, 10_000_000, 0)
    assert (result.draws, result.rollovers, result.violations) == (1, 24, 0)


def test_ten_thousand_hours_repeat_the_cycle_and_conserve() -> None:
    result = simulate_rollover(whale_and_small())
    assert (result.draws, result.rollovers) == (400, 9_600)
    assert result.paid == 4_000_000_000 and result.max_carried == 9_600_000
    assert result.violations == 0


def test_rank1_shares_track_the_capped_linear_odds() -> None:
    result = simulate(whale_and_small(), draws=2_000, seed="share")
    assert abs(float(result.rank1_share("w00")) - 0.05) < 0.015
    assert abs(float(result.class_rank1("small")) - 0.95) < 0.015
    assert abs(float(result.class_rank1("whale")) - float(result.class_odds("whale"))) < 0.015


def test_no_realized_cluster_share_beats_the_cap_by_more_than_noise() -> None:
    for pop in (whale_and_small(), equal_holders()):
        result = simulate(pop, draws=500, seed="cap")
        assert max(result.odds.values()) <= CAP_DEFAULT  # odds are exact
        assert max(result.slot_share(c) for c in result.odds) <= CAP_DEFAULT + Fraction(1, 100)


def test_report_has_real_generated_numbers() -> None:
    report = (ROOT / "reports" / "hourly_draw_fairness_2026-11.md").read_text()
    for heading in ("## (a)", "## (b)", "## (c)", "## (d)", "## Conservation"):
        assert heading in report
    assert "0 violations" in report and "| split 10, linked | 1 | 5.00% |" in report
