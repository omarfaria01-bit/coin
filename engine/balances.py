"""Running per-wallet reward balances (COIN_MATH v0.3.3 §13). Owner: Grok."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from engine.types import WalletId

# Defaults match COIN_MATH §13. Config/schema adoption is a later issue (gap A).
# MIN_PAYOUT_Q is in quote-asset base units (lamports when Q is SOL).
MIN_PAYOUT_Q_DEFAULT = 1_000_000  # 0.001 SOL
MIN_PAYOUT_Q_MAX = 5_000_000  # published maximum 0.005 SOL
UNCLAIMED_RECREDIT_SECONDS = 30 * 86_400
UNCLAIMED_TO_POT_SECONDS = 180 * 86_400


def clamp_min_payout(min_payout: int) -> int:
    """Reject negatives; cap at the published maximum of 0.005 SOL."""
    if isinstance(min_payout, bool) or not isinstance(min_payout, int):
        raise TypeError("min_payout must be an int")
    if min_payout < 0:
        raise ValueError(f"min_payout must be >= 0, got {min_payout}")
    return min(min_payout, MIN_PAYOUT_Q_MAX)


@dataclass(frozen=True, slots=True)
class WalletBalance:
    """Cumulative earned / paid / pending for one wallet, in Q base units."""

    wallet: WalletId
    earned_total: int = 0
    paid_total: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.earned_total, bool) or isinstance(self.paid_total, bool):
            raise TypeError("totals must be ints")
        if self.earned_total < 0 or self.paid_total < 0:
            raise ValueError("earned_total and paid_total must be >= 0")
        if self.paid_total > self.earned_total:
            raise ValueError("paid_total exceeds earned_total")

    @property
    def pending(self) -> int:
        return self.earned_total - self.paid_total


@dataclass(frozen=True, slots=True)
class ClaimEscrow:
    """Offline stub of one Merkle-distributor allocation (COIN_MATH §13 pull-back)."""

    wallet: WalletId
    amount: int
    escrowed_at: int
    claimed: bool = False
    recredited: bool = False
    returned_to_pot: bool = False

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("claim amount must be > 0")


def _check_amount(amount: int) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("amount must be an int")
    if amount < 0:
        raise ValueError(f"amount must be >= 0, got {amount}")


def credit(bal: WalletBalance, amount: int) -> WalletBalance:
    """Add holder rewards or draw prizes to earned_total.

    Pending never expires and is never clawed back for ineligibility.
    """
    _check_amount(amount)
    return WalletBalance(bal.wallet, bal.earned_total + amount, bal.paid_total)


def record_payment(bal: WalletBalance, amount: int) -> WalletBalance:
    """Move ``amount`` from pending to paid_total (push or distributor funding)."""
    _check_amount(amount)
    if amount > bal.pending:
        raise ValueError("payment exceeds pending")
    return WalletBalance(bal.wallet, bal.earned_total, bal.paid_total + amount)


def payable_amount(bal: WalletBalance, min_payout: int = MIN_PAYOUT_Q_DEFAULT) -> int:
    """Full pending if it meets the (clamped) threshold, otherwise 0."""
    threshold = clamp_min_payout(min_payout)
    return bal.pending if bal.pending >= threshold else 0


def apply_push(
    balances: Mapping[WalletId, WalletBalance],
    min_payout: int = MIN_PAYOUT_Q_DEFAULT,
) -> tuple[dict[WalletId, WalletBalance], dict[WalletId, int]]:
    """Pay every wallet whose pending reaches the threshold. Returns (book, transfers)."""
    updated: dict[WalletId, WalletBalance] = {}
    transfers: dict[WalletId, int] = {}
    for wid in sorted(balances):
        bal = balances[wid]
        pay = payable_amount(bal, min_payout)
        if pay:
            updated[wid] = record_payment(bal, pay)
            transfers[wid] = pay
        else:
            updated[wid] = bal
    return updated, transfers


def recredit_unclaimed(bal: WalletBalance, amount: int) -> WalletBalance:
    """30-day pull-back: amount previously marked paid returns to pending."""
    _check_amount(amount)
    if amount > bal.paid_total:
        raise ValueError("recredit exceeds paid_total")
    return WalletBalance(bal.wallet, bal.earned_total, bal.paid_total - amount)


def return_to_pot(
    bal: WalletBalance, amount: int, *, recredited: bool
) -> tuple[WalletBalance, int]:
    """180-day no-claim return (§13). Returns (balance, units the pot receives).

    This and payment are the only decreases of ``pending``; only unclaimed money
    goes back, and money the wallet already received is never touched.
    - Still escrowed (never recredited): the escrow is unclaimed, so ``amount``
      leaves both earned_total and paid_total; pending is unchanged.
    - Recredited at 30 days: the amount sits in pending and may since have been
      paid again. Take ``min(amount, pending)`` from earned_total only.
    """
    _check_amount(amount)
    if recredited:
        take = min(amount, bal.pending)
        return WalletBalance(bal.wallet, bal.earned_total - take, bal.paid_total), take
    if amount > bal.paid_total:
        raise ValueError("escrowed pot return exceeds paid_total")
    return WalletBalance(bal.wallet, bal.earned_total - amount, bal.paid_total - amount), amount


def credit_many(
    balances: Mapping[WalletId, WalletBalance],
    amounts: Mapping[WalletId, int],
) -> dict[WalletId, WalletBalance]:
    """Credit rewards or draw prizes onto a book. Missing wallets are created."""
    out = dict(balances)
    for wid in sorted(amounts):
        amt = amounts[wid]
        current = out.get(wid) or WalletBalance(wid)
        out[wid] = credit(current, amt)
    return out


def open_claims(
    balances: Mapping[WalletId, WalletBalance],
    amounts: Mapping[WalletId, int],
    escrowed_at: int,
) -> tuple[dict[WalletId, WalletBalance], tuple[ClaimEscrow, ...]]:
    """Fund a distributor: mark each amount paid and open an escrow stub."""
    out = dict(balances)
    claims: list[ClaimEscrow] = []
    for wid in sorted(amounts):
        amt = amounts[wid]
        if amt == 0:
            continue
        current = out.get(wid) or WalletBalance(wid)
        out[wid] = record_payment(current, amt)
        claims.append(ClaimEscrow(wallet=wid, amount=amt, escrowed_at=escrowed_at))
    return out, tuple(claims)


def mark_claimed(claim: ClaimEscrow) -> ClaimEscrow:
    if claim.claimed:
        raise ValueError("claim already marked claimed")
    if claim.recredited or claim.returned_to_pot:
        raise ValueError("claim already pulled back")
    return replace(claim, claimed=True)


def apply_pullbacks(
    balances: Mapping[WalletId, WalletBalance],
    claims: Sequence[ClaimEscrow],
    now: int,
) -> tuple[dict[WalletId, WalletBalance], tuple[ClaimEscrow, ...], int]:
    """Apply 30-day recredits and 180-day pot returns. Returns (book, claims, pot_in)."""
    out = dict(balances)
    updated: list[ClaimEscrow] = []
    pot_in = 0
    for claim in claims:
        if claim.claimed or claim.returned_to_pot:
            updated.append(claim)
            continue
        age = now - claim.escrowed_at
        if age >= UNCLAIMED_TO_POT_SECONDS:
            bal = out.get(claim.wallet) or WalletBalance(claim.wallet)
            out[claim.wallet], taken = return_to_pot(bal, claim.amount, recredited=claim.recredited)
            pot_in += taken
            updated.append(replace(claim, returned_to_pot=True))
            continue
        if (not claim.recredited) and age >= UNCLAIMED_RECREDIT_SECONDS:
            bal = out.get(claim.wallet) or WalletBalance(claim.wallet)
            out[claim.wallet] = recredit_unclaimed(bal, claim.amount)
            updated.append(replace(claim, recredited=True))
            continue
        updated.append(claim)
    return out, tuple(updated), pot_in
