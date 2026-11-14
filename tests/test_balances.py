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
    assert bal.pending == 100
    # "Ineligible this epoch" is a no-op on the book: no clawback, no expiry.
    still = credit(bal, 0)
    assert still == bal
    assert still.pending == 100
    grown = credit(still, 50)
    assert grown.pending == 150
    assert grown.pending > still.pending


def test_draw_prizes_use_the_same_balance() -> None:
    rewards = credit(_bal(), 400_000)
    with_draw = credit(rewards, 700_000)  # prize
    assert with_draw.earned_total == 1_100_000
    assert payable_amount(with_draw) == 1_100_000
    book, xfer = apply_push({W: with_draw, W2: credit(_bal(wallet=W2), 10)})
    assert xfer == {W: 1_100_000}
    assert book[W].pending == 0
    assert book[W2].pending == 10  # stays, never decreases
    # Conservation: pending_before = pending_after + transfers.
    before = with_draw.pending + 10
    after = book[W].pending + book[W2].pending + sum(xfer.values())
    assert before == after


def test_thirty_day_recredit_and_one_hundred_eighty_day_pot_return() -> None:
    start = credit_many({}, {W: 2_000_000})
    t0 = 1_700_000_000
    book, claims = open_claims(start, {W: 2_000_000}, escrowed_at=t0)
    assert book[W].pending == 0
    assert book[W].paid_total == 2_000_000
    # Before 30 days: no change.
    mid, claims_mid, pot = apply_pullbacks(book, claims, t0 + UNCLAIMED_RECREDIT_SECONDS - 1)
    assert pot == 0 and claims_mid[0].recredited is False
    assert mid[W].pending == 0
    # At 30 days: back to pending, to be offered again.
    rec, claims_rec, pot = apply_pullbacks(book, claims, t0 + UNCLAIMED_RECREDIT_SECONDS)
    assert pot == 0 and claims_rec[0].recredited is True
    assert rec[W].pending == 2_000_000
    assert rec[W].earned_total == 2_000_000
    # At 180 days, still unclaimed: returns to the pot, pending drops, never negative.
    gone, claims_gone, pot = apply_pullbacks(rec, claims_rec, t0 + UNCLAIMED_TO_POT_SECONDS)
    assert pot == 2_000_000
    assert claims_gone[0].returned_to_pot is True
    assert gone[W].pending == 0
    assert gone[W].earned_total == 0
    assert gone[W].paid_total == 0


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
    # 180d fires without a 30d recredit (clock jumped): both totals drop.
    bal = record_payment(credit(_bal(), 5), 5)
    out = return_to_pot(bal, 5)
    assert out.pending == 0 and out.earned_total == 0 and out.paid_total == 0


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


def test_rejects_invalid_values_and_180d_without_recredit() -> None:
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
    # 180d fires with no 30d recredit: still-escrowed path, pot gets the amount.
    start = credit(_bal(), 2_000_000)
    t0 = 50
    book, claims = open_claims({W: start}, {W: 2_000_000}, escrowed_at=t0)
    gone, out, pot = apply_pullbacks(book, claims, t0 + UNCLAIMED_TO_POT_SECONDS)
    assert pot == 2_000_000 and out[0].returned_to_pot is True and out[0].recredited is False
    assert gone[W].pending == 0 and gone[W].earned_total == 0
    seed = credit(_bal(), 5)
    funded, opened = open_claims({W: seed}, {W: 5}, escrowed_at=0)
    _book, rec_claims, _pot = apply_pullbacks(funded, opened, UNCLAIMED_RECREDIT_SECONDS)
    with pytest.raises(ValueError, match="already pulled"):
        mark_claimed(rec_claims[0])
