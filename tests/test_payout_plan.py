"""D46 holder payouts: snapshot state and the daily plan (#314)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from engine.holder_state import HolderState, apply_snapshot, day_inputs
from engine.loyalty import loyalty_multiplier
from engine.payout_plan import MintBook, payout_key, plan_mint
from engine.rewards import TOKEN_ACCOUNT_RENT_LAMPORTS

H = 3600
D0 = 1_763_424_000  # 2025-11-18T00:00:00Z, any midnight works
PRICE = Fraction(1, 1)  # 1 lamport per base unit


def snaps(seq, day="2026-11-18"):
    s = HolderState()
    for i, bal in enumerate(seq):
        s = apply_snapshot(s, bal, at=D0 + i * H, day=day)
    return s


M = loyalty_multiplier


def test_balance_hours_and_held_since():
    s = snaps([{"a": 100, "b": 50}, {"a": 80, "b": 50, "c": 999}, {"a": 120, "b": 50, "c": 999}])
    w = day_inputs(s)
    assert w["a"] == 80 * M(H) + 80 * M(2 * H)  # min of each pair: 100->80, 80->120
    assert w["b"] == 50 * M(H) + 50 * M(2 * H)
    assert w["c"] == 999 * M(H)  # earns from its second snapshot (first full hour)
    assert s.wallets["a"].held_since == D0 and s.wallets["c"].held_since == D0 + H


def test_launch_day_buyer_at_2130_rome_is_paid_for_three_hours():
    # D47: buy 20:30 UTC; snapshots at :40 -> 20:40, 21:40, 22:40, 23:40; export at 00:10 UTC.
    s = HolderState()
    for k in range(4):
        s = apply_snapshot(s, {"a": 1_000}, at=D0 + 20 * H + 40 * 60 + k * H, day="2026-11-18")
    assert day_inputs(s) == {"a": 1_000 * (M(H) + M(2 * H) + M(3 * H))}
    p = plan_mint(
        "M",
        MintBook(),
        wallet_balance=10**9,
        weights=day_inputs(s),
        lamports_per_unit=PRICE,
        day_index=1,
    )
    assert [(t.wallet, t.amount) for t in p.transfers] == [("a", 10**9)]


def test_buy_before_and_sell_after_one_snapshot_earns_nothing():
    s = snaps([{"x": 1}, {"x": 1, "flip": 10**9}, {"x": 1}])
    assert "flip" not in day_inputs(s)


def test_partial_sell_lowers_only_later_hours():
    full = day_inputs(snaps([{"a": 100}] * 4))["a"]
    part = day_inputs(snaps([{"a": 100}, {"a": 100}, {"a": 40}, {"a": 40}]))["a"]
    assert part == 100 * M(H) + 40 * M(2 * H) + 40 * M(3 * H) and full - part == 60 * (
        M(2 * H) + M(3 * H)
    )


def test_selling_to_zero_restarts_the_clock_and_new_day_resets_weight():
    s = snaps([{"a": 100}, {}, {"a": 100}])
    assert s.wallets["a"].held_since == D0 + 2 * H and s.wallets["a"].weight_today == 0
    s = apply_snapshot(s, {"a": 100}, at=D0 + 3 * H, day="2026-11-19")
    assert s.wallets["a"].weight_today == 100 * M(H) and s.snapshots_today == 1
    with pytest.raises(ValueError, match="after the previous"):
        apply_snapshot(s, {"a": 100}, at=D0 + 3 * H + 60, day="2026-11-19")


def test_state_json_round_trip_strict_keys_and_d46_migration():
    s = snaps([{"a": 1, "b": 2}, {"a": 3, "b": 2}])
    assert HolderState.from_json(s.to_json()) == s
    with pytest.raises(ValueError):
        HolderState.from_json({**s.to_json(), "x": 1})
    with pytest.raises(ValueError):
        apply_snapshot(s, {"a": -1}, at=D0 + 9 * H, day="2026-11-18")
    old = {
        "day": "d",
        "snapshots_today": 5,
        "wallets": {"a": {"held_since": 1, "day_min": 7, "last": 9}},
    }
    m = HolderState.from_json(old)
    assert m.last_at == 0 and m.wallets["a"].weight_today == 0 and m.wallets["a"].last == 9
    with pytest.raises(ValueError):
        HolderState.from_json({**old, "last_at": 0})  # new top level with old wallet keys


@given(
    st.lists(
        st.dictionaries(st.sampled_from("abcde"), st.integers(0, 10**12)), min_size=1, max_size=30
    ),
    st.integers(0, 10**13),
)
def test_balance_hours_conservation_property(seq, wallet_balance):
    s = snaps(seq)
    assert HolderState.from_json(s.to_json()) == s
    w = day_inputs(s)
    assert all(v > 0 for v in w.values())
    p = plan_mint(
        "M",
        MintBook(),
        wallet_balance=wallet_balance,
        weights=w,
        lamports_per_unit=PRICE,
        day_index=2,
    )
    assert p.credited == (wallet_balance if w else 0)
    assert p.credited == sum(t.amount for t in p.transfers) + p.book.owed


def test_key_is_per_day_mint_wallet():
    assert payout_key(3, "MintAbcdefghXYZ", "W") == "GTASP10:p3:MintAbcd:W"
    assert payout_key(3, "M1", "W") != payout_key(4, "M1", "W")


def test_plan_pays_above_rent_carries_dust_and_conserves():
    rent = TOKEN_ACCOUNT_RENT_LAMPORTS
    bal = {"big": 9_000, "small": 1_000}
    hold = {"big": 2 * H, "small": 2 * H}  # 2x multiplier for both
    budget = 10 * rent - 10  # small's 10% share is worth 1 lamport less than the rent
    p = plan_mint(
        "M",
        MintBook(),
        wallet_balance=budget,
        balances=bal,
        hold_seconds=hold,
        lamports_per_unit=PRICE,
        day_index=5,
    )
    paid = {t.wallet: t.amount for t in p.transfers}
    assert paid == {"big": 9 * rent - 9}
    assert p.book.carry == {"small": rent - 1}  # dust: carried, no account opened
    assert sum(paid.values()) + p.book.owed == p.credited == budget


def test_rerun_same_day_pays_nothing_twice():
    bal, hold = {"a": 1}, {"a": 2 * H}
    budget = 5 * TOKEN_ACCOUNT_RENT_LAMPORTS
    p1 = plan_mint(
        "M",
        MintBook(),
        wallet_balance=budget,
        balances=bal,
        hold_seconds=hold,
        lamports_per_unit=PRICE,
        day_index=7,
    )
    assert [t.amount for t in p1.transfers] == [budget]
    # same day, wallet already paid (tokens not yet sent: still in the wallet) -> no new transfer
    p2 = plan_mint(
        "M",
        p1.book,
        wallet_balance=budget,
        balances=bal,
        hold_seconds=hold,
        lamports_per_unit=PRICE,
        day_index=7,
    )
    assert p2.transfers == ()


def test_nobody_held_an_hour_leaves_budget_unassigned():
    p = plan_mint(
        "M",
        MintBook(),
        wallet_balance=10**9,
        balances={"a": 5},
        hold_seconds={"a": 59 * 60},
        lamports_per_unit=PRICE,
        day_index=1,
    )
    assert p.credited == 0 and p.transfers == () and p.book.owed == 0


def test_carry_is_not_spent_twice():
    book = MintBook(carry={"a": 100})
    p = plan_mint(
        "M",
        book,
        wallet_balance=100,
        balances={"b": 1},
        hold_seconds={"b": 2 * H},
        lamports_per_unit=PRICE,
        day_index=1,
    )
    assert p.budget == 0 and p.credited == 0  # the wallet only holds what is already owed to a


@given(
    st.dictionaries(st.sampled_from("abcdefgh"), st.integers(1, 10**12), min_size=1),
    st.integers(0, 10**13),
    st.integers(0, 40 * 24 * H),
    st.fractions(min_value=0, max_value=10, max_denominator=10**6),
)
def test_conservation_property(bal, wallet_balance, hold_s, price):
    hold = {w: hold_s for w in bal}
    p = plan_mint(
        "M",
        MintBook(carry={"z": 7}),
        wallet_balance=wallet_balance,
        balances=bal,
        hold_seconds=hold,
        lamports_per_unit=price,
        day_index=3,
    )
    assert 7 + p.credited == sum(t.amount for t in p.transfers) + p.book.owed
    assert p.credited <= max(0, wallet_balance - 7)
    assert all(t.amount > 0 for t in p.transfers)
