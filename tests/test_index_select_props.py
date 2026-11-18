"""Hypothesis properties for index/select.py: weights, prize split, membership (#193)."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from index.params import IndexParams
from index.select import BPS, select_members, split_prize, weights_bps

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))


def with_weights(mode: str, cap_pct: int) -> IndexParams:
    return P.model_copy(
        update={"weights": P.weights.model_copy(update={"mode": mode, "cap_pct": cap_pct})}
    )


def with_membership(size: int, enter: int, exit_: int) -> IndexParams:
    return P.model_copy(
        update={
            "membership": P.membership.model_copy(
                update={"size": size, "enter_rank": enter, "exit_rank": exit_}
            )
        }
    )


mints = st.integers(0, 10_000).map(lambda i: f"m{i}")
scores = st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False)


@st.composite
def weight_cases(draw):
    members = draw(st.lists(mints, min_size=1, max_size=30, unique=True))
    log_s = {m: draw(scores) for m in members}
    params = with_weights(
        draw(st.sampled_from(["equal", "score_capped"])), draw(st.integers(1, 100))
    )
    return members, log_s, params


@st.composite
def membership_cases(draw):
    size = draw(st.integers(1, 15))
    enter = draw(st.integers(1, size))
    exit_ = draw(st.integers(size, 25))
    ranked = draw(st.lists(mints, min_size=0, max_size=40, unique=True))
    prev = draw(
        st.lists(st.one_of(st.sampled_from(ranked), mints) if ranked else mints, max_size=15)
    )
    return ranked, prev, with_membership(size, enter, exit_)


# ------------------------------------------------------------------ weights


@given(weight_cases())
def test_weights_sum_to_10000_and_nonnegative(case) -> None:
    members, log_s, params = case
    w = weights_bps(members, log_s, params)
    assert list(w) == members
    assert sum(w.values()) == BPS
    assert all(isinstance(v, int) and v >= 0 for v in w.values())


@given(weight_cases(), st.randoms(use_true_random=False))
def test_weights_deterministic(case, rnd) -> None:
    members, log_s, params = case
    assert weights_bps(members, log_s, params) == weights_bps(members, log_s, params)
    # member order is the rank order; permuting only relabels ties, never the multiset sum
    shuffled = list(members)
    rnd.shuffle(shuffled)
    assert sum(weights_bps(shuffled, log_s, params).values()) == BPS


@given(weight_cases())
def test_weights_respect_cap_when_feasible(case) -> None:
    members, log_s, params = case
    cap_bps = params.weights.cap_pct * 100
    w = weights_bps(members, log_s, params)
    if params.weights.mode == "score_capped" and len(members) * cap_bps >= BPS:
        # largest remainder may add 1 bp to an uncapped member, never more
        assert max(w.values()) <= cap_bps + 1


# ------------------------------------------------------------------ prize split


@st.composite
def prize_cases(draw):
    members, log_s, params = draw(weight_cases())
    bps = weights_bps(members, log_s, params)
    return draw(st.integers(0, 10**18)), members, bps


@given(prize_cases())
def test_split_prize_conserves(case) -> None:
    lamports, members, bps = case
    parts = split_prize(lamports, members, bps)
    assert sum(parts.values()) == lamports
    assert set(parts) == set(members)
    assert all(isinstance(v, int) and v >= 0 for v in parts.values())


@given(prize_cases(), st.randoms(use_true_random=False))
def test_split_prize_deterministic_any_member_order(case, rnd) -> None:
    lamports, members, bps = case
    first = split_prize(lamports, members, bps)
    assert split_prize(lamports, members, bps) == first
    shuffled = list(members)
    rnd.shuffle(shuffled)
    again = split_prize(lamports, shuffled, bps)
    assert sum(again.values()) == lamports
    # only the remainder (rank-1 member) can differ with order
    for m in members:
        if m not in (members[0], shuffled[0]):
            assert again[m] == first[m]


@given(st.integers(0, 10**18))
def test_split_prize_no_members(lamports: int) -> None:
    if lamports == 0:
        assert split_prize(0, [], {}) == {}
    else:
        try:
            split_prize(lamports, [], {})
        except ValueError:
            return
        raise AssertionError("expected ValueError")


# ------------------------------------------------------------------ membership


@given(membership_cases())
def test_select_members_invariants(case) -> None:
    ranked, prev, params = case
    mp = params.membership
    out = select_members(ranked, prev, params)
    pos = {m: i + 1 for i, m in enumerate(ranked)}
    prev_set = set(prev)
    assert len(out) <= mp.size
    assert len(set(out)) == len(out)
    assert all(m in pos for m in out)
    assert [pos[m] for m in out] == sorted(pos[m] for m in out)
    assert len(out) == min(mp.size, len(ranked))
    eligible = [
        m for m in ranked if pos[m] <= mp.enter_rank or (m in prev_set and pos[m] <= mp.exit_rank)
    ]
    if len(eligible) >= mp.size:
        # buffer rule alone fills the basket: only eligible mints, best ranks first
        assert out == eligible[: mp.size]
    else:
        # short of `size`: every eligible mint stays, the rest is filled by rank
        assert set(eligible) <= set(out)


@given(membership_cases())
def test_select_members_deterministic_any_prev_order(case) -> None:
    ranked, prev, params = case
    assert select_members(ranked, prev, params) == select_members(
        ranked, list(reversed(prev)), params
    )


@given(membership_cases())
def test_select_members_prev_in_buffer_is_kept(case) -> None:
    ranked, prev, params = case
    mp = params.membership
    out = select_members(ranked, prev, params)
    top = set(ranked[: mp.enter_rank])
    assert top <= set(out)  # enter_rank <= size, so the top ranks always get in


@settings(max_examples=200)
@given(
    st.lists(mints, min_size=1, max_size=40, unique=True),
    st.integers(1, 15),
    st.data(),
)
def test_stable_ranking_returns_previous_members(ranked, size, data) -> None:
    enter = data.draw(st.integers(1, size))
    exit_ = data.draw(st.integers(size, 25))
    params = with_membership(size, enter, exit_)
    prev = ranked[:size]
    assert select_members(ranked, prev, params) == prev
    # and it stays a fixed point
    assert select_members(ranked, select_members(ranked, prev, params), params) == prev
