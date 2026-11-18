"""Holder state for the daily payout (D46). Pure: no I/O, no clock (times are passed in).

Hourly snapshots of the coin's holders feed two numbers per wallet:
- ``held_since``: the snapshot time at which the wallet's balance last went from 0 to > 0.
  Any snapshot with balance 0 (or absent) clears it, so the loyalty clock restarts.
- ``day_min``: the smallest balance seen in the day's snapshots. A wallet absent from any
  snapshot that day has 0. This is the balance that earns rewards for the day, so buying
  just before a snapshot and selling after earns nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class WalletState:
    held_since: int | None = None  # unix seconds
    day_min: int = 0
    last: int = 0


@dataclass
class HolderState:
    day: str = ""  # UTC date of the snapshots in day_min
    snapshots_today: int = 0
    wallets: dict[str, WalletState] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "day": self.day,
            "snapshots_today": self.snapshots_today,
            "wallets": {
                w: {"held_since": s.held_since, "day_min": s.day_min, "last": s.last}
                for w, s in sorted(self.wallets.items())
            },
        }

    @classmethod
    def from_json(cls, o: Mapping[str, object]) -> HolderState:
        if set(o) != {"day", "snapshots_today", "wallets"}:
            raise ValueError("bad holder state keys")
        wallets = {}
        for w, s in dict(o["wallets"]).items():  # type: ignore[arg-type]
            if set(s) != {"held_since", "day_min", "last"}:
                raise ValueError(f"bad wallet state keys for {w}")
            wallets[w] = WalletState(s["held_since"], int(s["day_min"]), int(s["last"]))
        return cls(str(o["day"]), int(o["snapshots_today"]), wallets)  # type: ignore[arg-type]


def apply_snapshot(
    state: HolderState, balances: Mapping[str, int], *, at: int, day: str
) -> HolderState:
    """Fold one snapshot (owner -> base units, excluded wallets already removed) into the state."""
    for w, b in balances.items():
        if isinstance(b, bool) or not isinstance(b, int) or b < 0:
            raise ValueError(f"bad balance for {w}")
    new_day = day != state.day
    out = HolderState(day, 1 if new_day else state.snapshots_today + 1, {})
    for w in sorted(set(state.wallets) | set(balances)):
        old = state.wallets.get(w, WalletState())
        bal = balances.get(w, 0)
        if bal == 0:
            held_since = None
        elif old.last == 0 or old.held_since is None:
            held_since = at
        else:
            held_since = old.held_since
        if new_day:
            day_min = bal
        elif w in state.wallets:
            day_min = min(old.day_min, bal)
        else:
            day_min = 0  # first seen after the day's first snapshot: not held all day
        if bal == 0 and held_since is None and day_min == 0:
            continue  # nothing left to remember
        out.wallets[w] = WalletState(held_since, day_min, bal)
    return out


def day_inputs(state: HolderState, *, at: int) -> tuple[dict[str, int], dict[str, int]]:
    """Day-minimum balances and holding seconds at `at`, for allocate_holder_rewards."""
    balances: dict[str, int] = {}
    hold: dict[str, int] = {}
    for w, s in sorted(state.wallets.items()):
        if s.day_min > 0 and s.held_since is not None:
            balances[w] = s.day_min
            hold[w] = max(0, at - s.held_since)
    return balances, hold
