"""Lot ledger per wallet, LIFO removal (COIN_MATH §1). Owner: Grok."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction

from engine.types import ClusterId, EventKind, Lot, LotSource, TokenEvent, WalletId


def _remove_lifo(lots: list[Lot], amount: int, wallet: WalletId, sig: str) -> None:
    remaining = amount
    while remaining > 0:
        if not lots:
            raise ValueError(f"oversell wallet={wallet} sig={sig}")
        last = lots[-1]
        if last.amount <= remaining:
            remaining -= last.amount
            lots.pop()
        else:
            lots[-1] = Lot(
                last.amount - remaining, last.cost_lamports_per_token, last.t_acquired, last.source
            )
            remaining = 0


def build_lots(
    events: Sequence[TokenEvent],
    excluded: frozenset[WalletId],
    twap_1h: Callable[[int], float],
) -> Mapping[WalletId, tuple[Lot, ...]]:
    """Replay events in (slot, sig, ix) order and return each wallet's lots at the end.

    BUY adds a POOL_BUY lot at the executed price; TRANSFER in adds a TRANSFER_IN lot at
    twap_1h(ts); SELL and TRANSFER out remove lots LIFO. Excluded accounts hold no lots.
    """
    lots: dict[WalletId, list[Lot]] = defaultdict(list)
    ordered = sorted(events, key=lambda e: (e.slot, e.sig, e.ix))
    for ev in ordered:
        if ev.amount <= 0:
            raise ValueError(f"bad event sig={ev.sig}")
        if ev.kind is EventKind.BUY:
            if ev.lamports is None or ev.dst is None:
                raise ValueError(f"bad event sig={ev.sig}")
            if ev.dst not in excluded:
                lots[ev.dst].append(
                    Lot(ev.amount, ev.lamports / ev.amount, ev.ts, LotSource.POOL_BUY)
                )
        elif ev.kind is EventKind.SELL:
            if ev.lamports is None or ev.src is None:
                raise ValueError(f"bad event sig={ev.sig}")
            if ev.src not in excluded:
                _remove_lifo(lots[ev.src], ev.amount, ev.src, ev.sig)
        elif ev.src is not None and ev.src == ev.dst:
            continue  # self-transfer is a no-op (keep age and cost basis)
        else:
            if ev.src is not None and ev.src not in excluded:
                _remove_lifo(lots[ev.src], ev.amount, ev.src, ev.sig)
            if ev.dst is not None and ev.dst not in excluded:
                lots[ev.dst].append(Lot(ev.amount, twap_1h(ev.ts), ev.ts, LotSource.TRANSFER_IN))
    return {wid: tuple(w_lots) for wid, w_lots in sorted(lots.items()) if w_lots}


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §1. Exact costs, origin, taint, cluster-internal moves.
# build_lots above stays for the v0.2 epoch until #82 wiring removes it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Origin:
    """The lot's original acquisition. Never overwritten (§1)."""

    sig: str
    ts: int
    cost_q: Fraction | None  # Q base units per token base unit; None if it entered by transfer


@dataclass(frozen=True, slots=True)
class LedgerLot:
    """``(amount, cost_Q, t_acquired, source, origin, tainted_until)`` of §1."""

    amount: int
    cost_q: Fraction | None
    t_acquired: int
    source: LotSource
    origin: Origin
    tainted_until: int = 0


def _take_lifo(lots: list[LedgerLot], amount: int, wallet: WalletId, sig: str) -> list[LedgerLot]:
    """Remove ``amount`` newest-first; return the removed pieces, oldest first."""
    taken: list[LedgerLot] = []
    remaining = amount
    while remaining > 0:
        if not lots:
            raise ValueError(f"oversell wallet={wallet} sig={sig}")
        last = lots[-1]
        if last.amount <= remaining:
            taken.append(lots.pop())
            remaining -= last.amount
        else:
            lots[-1] = replace(last, amount=last.amount - remaining)
            taken.append(replace(last, amount=remaining))
            remaining = 0
    taken.reverse()
    return taken


def build_ledger(
    events: Sequence[TokenEvent],
    excluded: frozenset[WalletId],
    cluster_of: Mapping[WalletId, ClusterId] | None = None,
    taint_until: Mapping[tuple[str, int], int] | None = None,
) -> dict[WalletId, tuple[LedgerLot, ...]]:
    """Rebuild every wallet's lots from the full event log under one cluster map.

    - BUY: a pool lot at the exact executed cost ``lamports / amount`` (fees incl.).
    - SELL / transfer out: lots leave LIFO from the sender (oldest lots stay).
    - Transfer inside one cluster: internal move, the pieces keep everything.
    - Transfer across clusters (or from an excluded account): age resets to the
      transfer time, ``source = transfer``, ``cost = None``; origin and taint travel.
    - Received pieces are always the receiver's newest lots (no-grief, §1).
    - ``taint_until[(sig, ix)] = t`` marks the pieces that event moves as tainted
      until ``t`` (vesting soft mode, §11); taint follows the lot, never shrinks.

    ``cluster_of`` maps wallets to cluster ids (missing → its own cluster). Call
    with the current map on the whole history: a later merge then makes earlier
    transfers internal, which restores age and cost (retroactive merge, §1).
    """
    clusters = cluster_of or {}
    taints = taint_until or {}
    lots: dict[WalletId, list[LedgerLot]] = defaultdict(list)
    for ev in sorted(events, key=lambda e: (e.slot, e.sig, e.ix)):
        if isinstance(ev.amount, bool) or ev.amount <= 0:
            raise ValueError(f"bad event sig={ev.sig}")
        if ev.kind is EventKind.BUY:
            if ev.lamports is None or ev.dst is None:
                raise ValueError(f"bad event sig={ev.sig}")
            if ev.dst not in excluded:
                cost = Fraction(ev.lamports, ev.amount)
                origin = Origin(ev.sig, ev.ts, cost)
                lots[ev.dst].append(LedgerLot(ev.amount, cost, ev.ts, LotSource.POOL_BUY, origin))
            continue
        if ev.kind is EventKind.SELL:
            if ev.lamports is None or ev.src is None:
                raise ValueError(f"bad event sig={ev.sig}")
            if ev.src not in excluded:
                _take_lifo(lots[ev.src], ev.amount, ev.src, ev.sig)
            continue
        if ev.src is not None and ev.src == ev.dst:
            continue  # self-transfer: no-op
        taint = taints.get((ev.sig, ev.ix), 0)
        if ev.src is None or ev.src in excluded:
            fresh = Origin(ev.sig, ev.ts, None)
            pieces = [LedgerLot(ev.amount, None, ev.ts, LotSource.TRANSFER_IN, fresh)]
            internal = False
        else:
            pieces = _take_lifo(lots[ev.src], ev.amount, ev.src, ev.sig)
            internal = ev.dst is not None and (
                clusters.get(ev.src, ev.src) == clusters.get(ev.dst, ev.dst)
            )
        if ev.dst is None or ev.dst in excluded:
            continue
        for piece in pieces:
            moved = (
                piece
                if internal
                else replace(piece, cost_q=None, t_acquired=ev.ts, source=LotSource.TRANSFER_IN)
            )
            if taint > moved.tainted_until:
                moved = replace(moved, tainted_until=taint)
            lots[ev.dst].append(moved)
    return {wid: tuple(w_lots) for wid, w_lots in sorted(lots.items()) if w_lots}
