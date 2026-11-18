"""Daily holder payout plan (D43, D46). Pure: no I/O, no clock.

Per basket mint: today's budget = what the system wallet holds of that mint minus what is
already owed (carry). It is split by balance x loyalty multiplier (`allocate_holder_rewards`),
added to each holder's carry, and paid only when the position is worth at least the
token-account rent (`settle_daily_rewards`). Everything not paid stays owed (carry).
Idempotency key per transfer: GTASP10:p<day>:<mint[:8]>:<wallet>.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from engine.rewards import allocate_holder_rewards, settle_daily_rewards


def payout_key(day_index: int, mint: str, wallet: str) -> str:
    if day_index < 0 or not mint or not wallet:
        raise ValueError("day_index >= 0, mint and wallet required")
    return f"GTASP10:p{day_index}:{mint[:8]}:{wallet}"


@dataclass
class MintBook:
    """What is owed per wallet for one basket mint, and the last day each wallet was paid."""

    carry: dict[str, int] = field(default_factory=dict)
    last_paid_day: dict[str, int] = field(default_factory=dict)

    @property
    def owed(self) -> int:
        return sum(self.carry.values())


@dataclass(frozen=True)
class Transfer:
    key: str
    wallet: str
    mint: str
    amount: int


@dataclass(frozen=True)
class MintPlan:
    mint: str
    budget: int
    credited: int
    transfers: tuple[Transfer, ...]
    book: MintBook


def plan_mint(
    mint: str,
    book: MintBook,
    *,
    wallet_balance: int,
    balances: Mapping[str, int],
    hold_seconds: Mapping[str, int],
    lamports_per_unit: Fraction,
    day_index: int,
) -> MintPlan:
    """One mint's day. Conservation: old owed + credited == paid + new owed."""
    if wallet_balance < 0 or lamports_per_unit < 0:
        raise ValueError("wallet_balance and price must be >= 0")
    budget = max(0, wallet_balance - book.owed)
    credit = allocate_holder_rewards(budget, balances, hold_seconds)
    credited = sum(credit.values())  # 0 when nobody has held >= 1h: the budget stays unassigned
    worth = {
        w: int((book.carry.get(w, 0) + credit.get(w, 0)) * lamports_per_unit)
        for w in set(book.carry) | set(credit)
    }
    s = settle_daily_rewards(
        book.carry,
        {w: a for w, a in credit.items() if a},
        worth,
        day_index=day_index,
        last_paid_day=book.last_paid_day,
    )
    transfers = tuple(
        Transfer(payout_key(day_index, mint, w), w, mint, a) for w, a in sorted(s.paid.items()) if a
    )
    new_book = MintBook(dict(s.carry), dict(s.last_paid_day))
    if book.owed + credited != sum(t.amount for t in transfers) + new_book.owed:
        raise AssertionError("payout plan not conserved")
    return MintPlan(mint, budget, credited, transfers, new_book)
