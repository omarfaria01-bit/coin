"""Cross-module properties from ENGINE_DESIGN §7.

Hypothesis uses max_examples=200 and derandomize=True so CI is reproducible.
#16 (vesting) is not on main yet; the lock-monotonicity test is xfail until then.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

import base58
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.draws import draw_winners, split_prizes
from engine.ledger import build_lots
from engine.merkle import claims_document
from engine.params import (
    ChurnParams,
    DrawParams,
    HoldParams,
    RewardParams,
    ScoringParams,
    UnderwaterParams,
)
from engine.rewards import allocate, capped_shares, epoch_budget, split_to_wallets
from engine.scoring import amount_weighted_hold, churn_factor, score, underwater_boost
from engine.twab import twab
from engine.types import EventKind, TokenEvent, WalletId

_SETTINGS = settings(
    max_examples=200,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
_CAP = ScoringParams().cap
_ALPHA = RewardParams().alpha_per_day
_HOLD, _CHURN, _UNDER = HoldParams(), ChurnParams(), UnderwaterParams()
_T0, _T1 = 0, 86_400
_PRICE = 10  # lamports per base unit (D13), constant so U does not move


def _wid(label: str) -> WalletId:
    return base58.b58encode(hashlib.sha256(f"prop:{label}".encode()).digest()).decode()


def _sig(label: str) -> str:
    return hashlib.sha256(f"sig:{label}".encode()).hexdigest()


def _buy(label: str, dst: WalletId, amount: int, ix: int = 0, sig: str | None = None) -> TokenEvent:
    return TokenEvent(
        slot=_T0,
        ts=_T0,
        sig=sig or _sig(label),
        ix=ix,
        kind=EventKind.BUY,
        src=None,
        dst=dst,
        amount=amount,
        lamports=amount * _PRICE,
        fee_payer=dst,
    )


def _transfer(
    label: str, src: WalletId, dst: WalletId, amount: int, ix: int, sig: str | None = None
) -> TokenEvent:
    return TokenEvent(
        slot=_T0,
        ts=_T0,
        sig=sig or _sig(label),
        ix=ix,
        kind=EventKind.TRANSFER,
        src=src,
        dst=dst,
        amount=amount,
        lamports=None,
        fee_payer=src,
    )


def _changes(events: list[TokenEvent], wallet: WalletId) -> list[tuple[int, int]]:
    bal = 0
    out: list[tuple[int, int]] = []
    for ev in sorted(events, key=lambda e: (e.slot, e.sig, e.ix)):
        delta = 0
        if ev.kind is EventKind.BUY and ev.dst == wallet:
            delta = ev.amount
        elif ev.kind is EventKind.SELL and ev.src == wallet:
            delta = -ev.amount
        elif ev.kind is EventKind.TRANSFER:
            if ev.dst == wallet:
                delta += ev.amount
            if ev.src == wallet:
                delta -= ev.amount
        if delta:
            bal += delta
            out.append((ev.ts, bal))
    return out


def _cluster_score(events: list[TokenEvent], members: set[WalletId]) -> float:
    """B̄·H·F·U for one cluster. Callers keep all lots at ts=t0 so H=1 (age 0)."""
    lots_map = build_lots(events, frozenset(), lambda _t: float(_PRICE))
    lots = [lot for wid in members for lot in lots_map.get(wid, ())]
    bar = sum(twab(0, _changes(events, wid), _T0, _T1) for wid in members)
    v_buy = v_sell = 0
    for ev in events:
        if ev.kind is EventKind.BUY and ev.dst in members:
            v_buy += ev.amount
        elif ev.kind is EventKind.SELL and ev.src in members:
            v_sell += ev.amount
    # Evaluate at t0: every lot is age 0, so H=1; lots are too young for U, so U=1.
    hold = amount_weighted_hold(lots, _T0, _HOLD)
    churn = churn_factor(v_buy, v_sell, bar, _CHURN)
    boost = underwater_boost(lots, float(_PRICE), _T0, _UNDER) if lots else 1.0
    return score(bar, hold, churn, boost)


def _allocate(
    events: list[TokenEvent], cluster_of: dict[WalletId, WalletId], budget: int
) -> tuple[dict[str, int], int, dict[str, float]]:
    members: dict[str, set[WalletId]] = defaultdict(set)
    for wid, cid in cluster_of.items():
        members[cid].add(wid)
    scores = {cid: _cluster_score(events, group) for cid, group in members.items()}
    shares = capped_shares(scores, _CAP)
    payouts, rollover = allocate(budget, shares)
    return payouts, rollover, shares


@_SETTINGS
@given(
    st.integers(2_000, 50_000),
    st.integers(2_000, 50_000),
    st.integers(1, 1_000),
    st.integers(1, 20_000),
)
def test_intra_cluster_transfer_does_not_change_payout(
    amt_a: int, amt_b: int, xfer: int, others: int
) -> None:
    """TRANSFER inside a cluster must not change that cluster's allocate() payout.

    Transfers reset lot age (ledger). This property is asserted only with the hold
    horizon effect disabled: every event is at t0 and scores are evaluated at t0,
    so every lot has age 0 and H=1. There are no sells, and lots are younger than
    the 48h underwater gate, so F=U=1. The remaining effect is cluster TWAB, which
    a same-timestamp intra-cluster transfer conserves.

    N=21 equal-sized outside clusters keeps the cap from binding (1/21 < 0.05).
    """
    xfer = min(xfer, amt_a)
    a, b = _wid("a"), _wid("b")
    outsiders = [_wid(f"o{i}") for i in range(20)]
    cid_c = min(a, b)
    cluster_of = {a: cid_c, b: cid_c, **{w: w for w in outsiders}}
    # One signature, increasing ix, so the transfer cannot sort before the buys
    # (build_lots orders by (slot, sig, ix) and would otherwise oversell).
    sig = _sig("block")
    base = [_buy("a", a, amt_a, ix=0, sig=sig), _buy("b", b, amt_b, ix=1, sig=sig)]
    base += [_buy(f"o{i}", w, others, ix=2 + i, sig=sig) for i, w in enumerate(outsiders)]
    moved = [*base, _transfer("ab", a, b, xfer, ix=100, sig=sig)]
    budget = 10**12
    before, _, _ = _allocate(base, cluster_of, budget)
    after, _, _ = _allocate(moved, cluster_of, budget)
    assert before[cid_c] == after[cid_c]


@_SETTINGS
@given(
    st.integers(21, 30),
    st.integers(10_000, 1_000_000),
    st.integers(1, 9_999),
    st.integers(10**9, 10**16),
)
def test_splitting_a_wallet_does_not_increase_reward(
    n: int, amount: int, frac_bps: int, pot: int
) -> None:
    """No clustering, cap not binding (n≥21): splitting one wallet must not raise Σ payouts."""
    frac = frac_bps / 10_000
    part = max(1, int(amount * frac))
    rest = amount - part
    if rest <= 0:
        rest, part = 1, amount - 1
    field = [_wid(f"f{i}") for i in range(n)]
    left, right = _wid("s0"), _wid("s1")
    budget = epoch_budget(pot, _ALPHA, 24)

    def payout_sum(wallets: list[WalletId], amounts: list[int]) -> int:
        events = [
            _buy(f"b{i}", w, amt, ix=0)
            for i, (w, amt) in enumerate(zip(wallets, amounts, strict=True))
        ]
        cluster_of = {w: w for w in wallets}
        payouts, _, shares = _allocate(events, cluster_of, budget)
        assert all(s <= _CAP + 1e-12 for s in shares.values())
        return sum(payouts.values())

    base_amts = [amount] * n
    split_wallets = [left, right, *field[1:]]
    split_amts = [part, rest, *base_amts[1:]]
    before = payout_sum(field, base_amts)
    after = payout_sum(split_wallets, split_amts)
    # ±N lamports of floor across the post-split set.
    assert after <= before + len(split_wallets)


@_SETTINGS
@given(
    st.integers(21, 28),
    st.lists(st.integers(1_000, 100_000), min_size=21, max_size=28),
    st.integers(0, 10**18),
)
def test_payouts_rollover_and_dust_sum_to_epoch_budget(
    n: int, amounts: list[int], pot: int
) -> None:
    """Σ payouts + rollover + dust == R_e exactly (ENGINE_DESIGN §7)."""
    amounts = (amounts + [1_000] * n)[:n]
    wallets = [_wid(f"w{i}") for i in range(n)]
    events = [_buy(f"b{i}", w, amounts[i], ix=0) for i, w in enumerate(wallets)]
    cluster_of = {w: w for w in wallets}
    budget = epoch_budget(pot, _ALPHA, 24)
    payouts, rollover, shares = _allocate(events, cluster_of, budget)
    assert all(s <= _CAP + 1e-12 for s in shares.values())
    paid = 0
    dust_total = 0
    lots_map = build_lots(events, frozenset(), lambda _t: float(_PRICE))
    for cid, payout in payouts.items():
        weights = {}
        for wid in (cid,):  # one wallet per cluster in this test
            bar = twab(0, _changes(events, wid), _T0, _T1)
            hold = amount_weighted_hold(lots_map.get(wid, ()), _T0, _HOLD)
            weights[wid] = bar * hold
        amts, dust = split_to_wallets(payout, weights)
        paid += sum(amts.values())
        dust_total += dust
    assert paid + rollover + dust_total == budget


def _vesting_ready() -> bool:
    from engine.vesting import locked_amount

    try:
        locked_amount(10, 0.0)
    except NotImplementedError:
        return False
    return True


@_SETTINGS
@given(
    st.lists(
        st.tuples(
            st.integers(0, 14 * 86_400),
            st.floats(0, 1e6, allow_nan=False, allow_infinity=False),
        ),
        min_size=1,
        max_size=20,
    ),
    st.floats(0.01, 1e6, allow_nan=False, allow_infinity=False),
    st.integers(1, 10**12),
)
@pytest.mark.xfail(
    not _vesting_ready(), reason="blocked on #16 (vesting stub on main)", strict=False
)
def test_locked_amount_never_increases(
    steps: list[tuple[int, float]], p_entry: float, vested: int
) -> None:
    from engine.params import VestingParams
    from engine.vesting import locked_amount, unlocked_fraction

    prev = 0.0
    prev_locked = locked_amount(vested, prev)
    p = VestingParams()
    for t, twap in steps:
        prev = unlocked_fraction(prev, t, 0, twap, p_entry, p)
        locked = locked_amount(vested, prev)
        assert 0 <= locked <= vested
        assert locked <= prev_locked
        prev_locked = locked


@_SETTINGS
@given(
    st.dictionaries(
        st.text(min_size=1, max_size=6, alphabet="abcXYZ"),
        st.floats(0.01, 1e6, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=12,
    ),
    st.binary(min_size=8, max_size=32),
    st.integers(1, 8),
    st.integers(0, 10**18),
)
def test_draws_and_claims_are_byte_identical_for_the_same_inputs(
    scores: dict[str, float], randomness: bytes, k: int, pot: int
) -> None:
    shuffled = {key: scores[key] for key in reversed(list(scores))}
    assert draw_winners(scores, randomness, k) == draw_winners(shuffled, randomness, k)
    winners = draw_winners(scores, randomness, k)
    split = DrawParams().prize_split
    prizes_a, rem_a = split_prizes(pot, winners, split)
    prizes_b, rem_b = split_prizes(pot, list(winners), split)
    assert prizes_a == prizes_b and rem_a == rem_b
    payouts = {w: max(1, prizes_a.get(w, 0) + 1) for w in prizes_a} or {_wid("solo"): 1}
    # claims_document needs 32-byte base58 ids; draw ids above may be short labels.
    hashed = {_wid(name): amt for name, amt in payouts.items()}
    assert claims_document(hashed, 7) == claims_document(dict(reversed(list(hashed.items()))), 7)
