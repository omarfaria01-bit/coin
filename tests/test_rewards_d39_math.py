"""D39 (audit #271 C1/H1/H2): linear odds proofs as properties, plus the split table."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine.hourly_draw import (
    MIN_HOLDING_SHARE_DEFAULT,
    draw_weights,
    plan_hourly_draw,
    supply_capped_score,
)
from sim.rewards_d39_sybil import SPLITS, proportional, table

S = 10**15
LOW_MIN = Fraction(1, 10**12)


def share(bal: dict[str, int], who: str = "a", min_holding: Fraction = LOW_MIN) -> Fraction:
    scores = {c: 5 * b for c, b in bal.items()}
    w = draw_weights(scores, bal, S, min_holding_share=min_holding)
    return Fraction(sum(v for c, v in w.items() if c.startswith(who)), sum(w.values()))


honest = st.lists(st.integers(10**9, S // 400), min_size=120, max_size=200)


@given(honest, st.integers(10**9, S // 100), st.integers(2, 40))
@settings(max_examples=60, deadline=None)
def test_split_gives_exactly_the_same_total_odds(h: list[int], a: int, n: int) -> None:
    """No group capped → odds are Σ s_i / Σ s, so any split of a is invariant (proof 1)."""
    base = {f"h{i:03d}": b for i, b in enumerate(h)}
    assume(max([*h, a]) * 20 < sum(h) + a)  # no group at the 5% odds cap
    parts = [a // n + (1 if i < a % n else 0) for i in range(n)]
    one = share(base | {"a0": a})
    many = share(base | {f"a{i:03d}": p for i, p in enumerate(parts)})
    assert one == many == Fraction(a, a + sum(h))


@given(honest, st.lists(st.integers(10**9, S // 5), min_size=2, max_size=12))
@settings(max_examples=60, deadline=None)
def test_merging_never_helps_and_split_never_beats_proportional(h: list[int], parts: list[int]):
    """Proofs 2–3, caps included (5% supply, 5% odds)."""
    base = {f"h{i:03d}": b for i, b in enumerate(h)}
    assume(max(h) * 20 < sum(h))  # honest groups uncapped, so "proportional" is well defined
    merged = share(base | {"a0": sum(parts)})
    split = share(base | {f"a{i:03d}": p for i, p in enumerate(parts)})
    assert merged <= split <= Fraction(sum(parts), sum(parts) + sum(h))


@given(st.integers(0, 10**20), st.integers(1, 10**20))
def test_supply_cap_is_score_on_min_balance(score: int, bal: int) -> None:
    capped = supply_capped_score(score, bal, S)
    assert capped == Fraction(score) * min(bal, S // 20) / bal
    assert capped <= score


def test_split_table_1_10_100_1000_wallets() -> None:
    small = table(Fraction(3, 100))
    d39 = [row[3] for row in small]  # minimum lowered: pure invariance
    assert len(set(d39)) == 1 and d39[0] == proportional(3 * S // 100)
    assert [row[2] for row in small][:3] == d39[:3]  # defaults: same for 1/10/100 wallets
    assert small[3][2] == 0  # 1,000 × 0.003% < 0.01% minimum: dust gets nothing
    sqrt_old = [row[1] for row in small]
    assert sqrt_old == sorted(sqrt_old) and sqrt_old[-1] > 6 * sqrt_old[0]  # old rule paid splits
    whale = table(Fraction(20, 100))
    assert all(row[2] <= proportional(S // 5) for row in whale)
    assert whale[0][2] == Fraction(1, 20)  # unsplit: 5% of supply, then 5% of the odds
    assert SPLITS == (1, 10, 100, 1000)


def _kw(**kw):
    base = {
        "genesis_hash": b"g" * 32, "mint": b"m" * 32, "draw_index": 1,
        "snapshot_hash": b"s" * 32, "rho": b"r" * 32, "total_supply": S,
    }  # fmt: skip
    return base | kw


def test_under_100_groups_rolls_over_never_equal_odds() -> None:
    bal = {f"h{i:02d}": S // 1000 for i in range(99)}
    p = plan_hourly_draw(bal, 10**9, (10_000,), balances=bal, **_kw())
    assert (p.drawn, p.reason, p.rollover, p.eligible) == (False, "too_few_groups", 10**9, 99)
    bal |= {"h99": S // 1000}
    assert plan_hourly_draw(bal, 10**9, (10_000,), balances=bal, **_kw()).drawn


def test_dust_below_minimum_holding_is_not_eligible() -> None:
    bal = {f"h{i:03d}": S // 1000 for i in range(100)} | {"dust": S // 10**6}
    scores = dict(bal)
    w = draw_weights(scores, bal, S)
    assert "dust" not in w and len(w) == 100
    assert Fraction(1, 10_000) == MIN_HOLDING_SHARE_DEFAULT
    # min_groups can never go below 1/cap + 1 = 21 (the old equal-odds branch is unreachable)
    small = {f"h{i:02d}": S // 1000 for i in range(20)}
    p = plan_hourly_draw(small, 10**9, (10_000,), balances=small, **_kw(min_groups=1))
    assert p.reason == "too_few_groups"
