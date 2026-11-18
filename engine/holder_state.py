"""Holder state for the daily payout (D46, D47). Pure: no I/O, no clock (times are passed in).

Hourly snapshots of the coin's holders feed two numbers per wallet:
- ``held_since``: the snapshot time at which the wallet's balance last went from 0 to > 0.
  Any snapshot with balance 0 (or absent) clears it, so the loyalty clock restarts.
- ``weight_today`` (D47, balance-hours): for each pair of consecutive snapshots, the wallet
  earns ``min(previous, current)`` balance times the loyalty multiplier at the current snapshot.
  Absent or 0 in either snapshot earns 0, so buying just before a snapshot and selling after
  earns nothing, and a partial sell lowers only the hours after it. One pair is one hour: a
  missed snapshot earns nothing for that hour. An hour belongs to the UTC day of the snapshot
  that closes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from engine.loyalty import loyalty_multiplier

MIN_GAP_SECONDS = 1800  # two snapshots closer than this would count one hour twice


@dataclass
class WalletState:
    held_since: int | None = None  # unix seconds
    weight_today: Fraction = Fraction(0)
    last: int = 0


@dataclass
class HolderState:
    day: str = ""  # UTC date of the hours in weight_today
    snapshots_today: int = 0
    last_at: int = 0  # unix seconds of the latest snapshot
    wallets: dict[str, WalletState] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "day": self.day,
            "snapshots_today": self.snapshots_today,
            "last_at": self.last_at,
            "wallets": {
                w: {"held_since": s.held_since, "weight_today": str(s.weight_today), "last": s.last}
                for w, s in sorted(self.wallets.items())
            },
        }

    @classmethod
    def from_json(cls, o: Mapping[str, object]) -> HolderState:
        """Strict keys. A D46 state (``day_min``, no ``last_at``) loads with today's weight 0."""
        legacy = set(o) == {"day", "snapshots_today", "wallets"}
        if not legacy and set(o) != {"day", "snapshots_today", "last_at", "wallets"}:
            raise ValueError("bad holder state keys")
        wallets = {}
        for w, s in dict(o["wallets"]).items():  # type: ignore[arg-type]
            keys = {"held_since", "day_min" if legacy else "weight_today", "last"}
            if set(s) != keys:
                raise ValueError(f"bad wallet state keys for {w}")
            weight = Fraction(0) if legacy else Fraction(str(s["weight_today"]))
            if weight < 0:
                raise ValueError(f"negative weight for {w}")
            wallets[w] = WalletState(s["held_since"], weight, int(s["last"]))
        last_at = 0 if legacy else int(o["last_at"])  # type: ignore[call-overload]
        return cls(str(o["day"]), int(o["snapshots_today"]), last_at, wallets)  # type: ignore[call-overload]


def apply_snapshot(
    state: HolderState, balances: Mapping[str, int], *, at: int, day: str
) -> HolderState:
    """Fold one snapshot (owner -> base units, excluded wallets already removed) into the state."""
    for w, b in balances.items():
        if isinstance(b, bool) or not isinstance(b, int) or b < 0:
            raise ValueError(f"bad balance for {w}")
    if state.last_at and at - state.last_at < MIN_GAP_SECONDS:
        raise ValueError(f"snapshot {at - state.last_at}s after the previous one")
    new_day = day != state.day
    out = HolderState(day, 1 if new_day else state.snapshots_today + 1, at, {})
    for w in sorted(set(state.wallets) | set(balances)):
        old = state.wallets.get(w, WalletState())
        bal = balances.get(w, 0)
        if bal == 0:
            held_since = None
        elif old.last == 0 or old.held_since is None:
            held_since = at
        else:
            held_since = old.held_since
        credit = min(old.last, bal)
        hour = Fraction(0)
        if credit > 0 and held_since is not None:
            hour = credit * loyalty_multiplier(at - held_since)
        weight = (Fraction(0) if new_day else old.weight_today) + hour
        if bal == 0 and weight == 0:
            continue  # nothing left to remember
        out.wallets[w] = WalletState(held_since, weight, bal)
    return out


def day_inputs(state: HolderState) -> dict[str, Fraction]:
    """The day's balance-hour weights (> 0 only), for the pro-rata split of the payout."""
    return {w: s.weight_today for w, s in sorted(state.wallets.items()) if s.weight_today > 0}
