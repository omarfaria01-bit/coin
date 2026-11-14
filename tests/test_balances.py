"""Tests for engine/balances.py (COIN_MATH v0.3.3 §13)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.balances import (
    MIN_PAYOUT_Q_DEFAULT,
    MIN_PAYOUT_Q_MAX,
    UNCLAIMED_RECREDIT_SECONDS,
    UNCLAIMED_TO_POT_SECONDS,
    WalletBalance,
    apply_pullbacks,
    apply_push,
    clamp_min_payout,
    credit,
    credit_many,
    mark_claimed,
    open_claims,
    payable_amount,
    record_payment,
    return_to_pot,
)

W = "wal1"
W2 = "wal2"


def _bal(earned: int = 0, paid: int = 0, wallet: str = W) -> WalletBalance:
    return WalletBalance(wallet, earned, paid)


def test_pending_identity_and_threshold() -> None:
    assert clamp_min_payout(MIN_PAYOUT_Q_DEFAULT) == 1_000_000
    assert clamp_min_payout(10_000_000) == MIN_PAYOUT_Q_MAX
    with pytest.raises(ValueError, match="min_payout"):
        clamp_min_payout(-1)
    dust = credit(_bal(), MIN_PAYOUT_Q_DEFAULT - 1)
    assert dust.pending == MIN_PAYOUT_Q_DEFAULT - 1
    assert payable_amount(dust) == 0
    # A later credit that crosses the threshold pays the *full* pending.
    crossed = credit(dust, 2)
    assert payable_amount(crossed) == MIN_PAYOUT_Q_DEFAULT + 1
    paid = record_payment(crossed, payable_amount(crossed))
    assert paid.pending == 0
    assert paid.earned_total == MIN_PAYOUT_Q_DEFAULT + 1
    assert paid.paid_total == paid.earned_total


def test_below_threshold_never_decreases_and_ineligibility_does_not_claw_back() -> None:
    bal = credit(_bal(), 100)
    assert credit(bal, 0) == bal  # "ineligible this epoch" is a no-op: no clawback, no expiry
    assert credit(bal, 50).pending == 150


def test_draw_prizes_use_the_same_balance() -> None:
    rewards = credit(_bal(), 400_000)
    with_draw = credit(rewards, 700_000)  # prize
    assert with_draw.earned_total == 1_100_000
    assert payable_amount(with_draw) == 1_100_000
    book, xfer = apply_push({W: with_draw, W2: credit(_bal(wallet=W2), 10)})
    assert xfer == {W: 1_100_000}
    assert book[W].pending == 0
    assert book[W2].pending == 10  # stays, never decreases


def test_thirty_day_recredit_and_one_hundred_eighty_day_pot_return() -> None:
    start = credit_many({}, {W: 2_000_000})
    t0 = 1_700_000_000
    book, claims = open_claims(start, {W: 2_000_000}, escrowed_at=t0)
    assert book[W].pending == 0
    assert book[W].paid_total == 2_000_000
    _, claims_mid, pot = apply_pullbacks(book, claims, t0 + UNCLAIMED_RECREDIT_SECONDS - 1)
    assert pot == 0 and claims_mid[0].recredited is False  # before 30 days: no change
    # At 30 days: back to pending, to be offered again.
    rec, claims_rec, pot = apply_pullbacks(book, claims, t0 + UNCLAIMED_RECREDIT_SECONDS)
    assert pot == 0 and claims_rec[0].recredited is True
    assert rec[W].pending == rec[W].earned_total == 2_000_000
    # At 180 days, still unclaimed: returns to the pot, pending drops, never negative.
    gone, claims_gone, pot = apply_pullbacks(rec, claims_rec, t0 + UNCLAIMED_TO_POT_SECONDS)
    assert pot == 2_000_000
    assert claims_gone[0].returned_to_pot is True
    assert gone[W] == WalletBalance(W, 0, 0)


def test_claimed_escrow_is_not_pulled_back() -> None:
    start = credit(_bal(), 2_000_000)
    t0 = 10
    book, claims = open_claims({W: start}, {W: 2_000_000}, escrowed_at=t0)
    claimed = (mark_claimed(claims[0]),)
    later, out, pot = apply_pullbacks(book, claimed, t0 + UNCLAIMED_TO_POT_SECONDS)
    assert pot == 0
    assert out[0].claimed is True
    assert later[W].pending == 0
    assert later[W].paid_total == 2_000_000
    with pytest.raises(ValueError, match="already"):
        mark_claimed(out[0])


def test_return_to_pot_while_still_escrowed() -> None:
    # Escrowed 5 plus 7 fresh pending: only the escrow leaves; pending is untouched.
    bal = credit(record_payment(credit(_bal(), 5), 5), 7)
    out, taken = return_to_pot(bal, 5, recredited=False)
    assert taken == 5 and out.pending == 7 and out.paid_total == 0


def test_recredit_then_paid_then_180d_takes_nothing() -> None:
    # Review repro (#70): recredit, push pays it, 180d must not erase the payment.
    t0 = 0
    book, claims = open_claims(credit_many({}, {W: 100}), {W: 100}, escrowed_at=t0)
    book, claims, _ = apply_pullbacks(book, claims, t0 + UNCLAIMED_RECREDIT_SECONDS)
    book, xfer = apply_push(book, min_payout=1)
    assert xfer == {W: 100}
    paid = book[W]
    book, claims, pot = apply_pullbacks(book, claims, t0 + UNCLAIMED_TO_POT_SECONDS)
    assert pot == 0 and book[W] == paid and claims[0].returned_to_pot is True


_OPS = st.lists(
    st.tuples(st.sampled_from(["credit", "push", "open", "claim", "pull"]), st.integers(0, 500)),
    max_size=30,
)


@given(_OPS)
@settings(max_examples=150, deadline=None)
def test_property_earned_minus_paid_minus_pot_is_conserved(ops: list[tuple[str, int]]) -> None:
    # Σ credited == earned_total + pot_in, and pending/paid stay consistent.
    book: dict[str, WalletBalance] = {W: _bal()}
    claims: tuple = ()
    credited = pot_total = now = 0
    for op, x in ops:
        if op == "credit":
            book, credited = credit_many(book, {W: x}), credited + x
        elif op == "push":
            book, _ = apply_push(book, min_payout=1)
        elif op == "open" and book[W].pending:
            book, new = open_claims(book, {W: min(x + 1, book[W].pending)}, escrowed_at=now)
            claims += new
        elif (
            op == "claim"
            and claims
            and not (claims[0].recredited or claims[0].claimed or claims[0].returned_to_pot)
        ):
            claims = (mark_claimed(claims[0]), *claims[1:])
        elif op == "pull":
            now += x * 86_400
            book, claims, pot = apply_pullbacks(book, claims, now)
            pot_total += pot
        assert book[W].pending >= 0 and book[W].paid_total <= book[W].earned_total
        assert credited == book[W].earned_total + pot_total


@given(
    st.integers(0, 10**9),
    st.integers(0, 10**9),
    st.integers(0, MIN_PAYOUT_Q_MAX * 2),
)
@settings(max_examples=80, deadline=None)
def test_invariants_credit_then_push(earned: int, extra: int, min_payout: int) -> None:
    bal = credit(credit(_bal(), earned), extra)
    assert bal.pending == bal.earned_total - bal.paid_total >= 0
    book, xfer = apply_push({W: bal}, min_payout)
    after = book[W]
    assert after.pending == after.earned_total - after.paid_total >= 0
    paid = xfer.get(W, 0)
    assert bal.pending == after.pending + paid
    threshold = min(min_payout, MIN_PAYOUT_Q_MAX)
    if bal.pending >= threshold:
        assert paid == bal.pending and after.pending == 0
    else:
        assert paid == 0 and after.pending == bal.pending


def test_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        WalletBalance(W, earned_total=-1)
    with pytest.raises(ValueError):
        WalletBalance(W, earned_total=1, paid_total=2)
    with pytest.raises(ValueError, match="amount"):
        credit(_bal(), -1)
    with pytest.raises(ValueError, match="exceeds pending"):
        record_payment(credit(_bal(), 5), 6)
    with pytest.raises(TypeError):
        clamp_min_payout(True)  # type: ignore[arg-type]
    seed = credit(_bal(), 5)
    funded, opened = open_claims({W: seed}, {W: 5}, escrowed_at=0)
    _book, rec_claims, _pot = apply_pullbacks(funded, opened, UNCLAIMED_RECREDIT_SECONDS)
    with pytest.raises(ValueError, match="already pulled"):
        mark_claimed(rec_claims[0])
