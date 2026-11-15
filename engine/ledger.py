"""Lot ledger per wallet, LIFO removal (COIN_MATH §1). Owner: Grok."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction

from engine.types import ClusterId, EventKind, LotSource, TokenEvent, WalletId

# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §1. Exact costs, origin, taint, cluster-internal moves.
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
        _apply_event(ev, lots, excluded, clusters, taints)
    return {wid: tuple(w_lots) for wid, w_lots in sorted(lots.items()) if w_lots}


def _apply_event(
    ev: TokenEvent,
    lots: dict[WalletId, list[LedgerLot]],
    excluded: frozenset[WalletId],
    clusters: Mapping[WalletId, ClusterId],
    taints: Mapping[tuple[str, int], int],
) -> None:
    """Apply one event to the per-wallet lot lists (rules in :func:`build_ledger`)."""
    if isinstance(ev.amount, bool) or ev.amount <= 0:
        raise ValueError(f"bad event sig={ev.sig}")
    if ev.kind is EventKind.BUY:
        if ev.lamports is None or ev.dst is None:
            raise ValueError(f"bad event sig={ev.sig}")
        if ev.dst not in excluded:
            cost = Fraction(ev.lamports, ev.amount)
            origin = Origin(ev.sig, ev.ts, cost)
            lots[ev.dst].append(LedgerLot(ev.amount, cost, ev.ts, LotSource.POOL_BUY, origin))
        return
    if ev.kind is EventKind.SELL:
        if ev.lamports is None or ev.src is None:
            raise ValueError(f"bad event sig={ev.sig}")
        if ev.src not in excluded:
            _take_lifo(lots[ev.src], ev.amount, ev.src, ev.sig)
        return
    if ev.src is not None and ev.src == ev.dst:
        return  # self-transfer: no-op
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
        return
    for piece in pieces:
        moved = (
            piece
            if internal
            else replace(piece, cost_q=None, t_acquired=ev.ts, source=LotSource.TRANSFER_IN)
        )
        if taint > moved.tainted_until:
            moved = replace(moved, tainted_until=taint)
        lots[ev.dst].append(moved)


Segment = tuple[int, int, tuple[LedgerLot, ...]]


def ledger_segments(
    events: Sequence[TokenEvent],
    excluded: frozenset[WalletId],
    t0: int,
    t1: int,
    cluster_of: Mapping[WalletId, ClusterId] | None = None,
    taint_until: Mapping[tuple[str, int], int] | None = None,
) -> dict[WalletId, list[Segment]]:
    """Each wallet's lots as a step function of the second over ``[t0, t1)`` (§0, §1).

    Returns ``wallet → [(a, b, lots)]``: the wallet held exactly ``lots`` in every
    second ``a ≤ t < b``. The state of second ``t`` is after all events with
    ``ts ≤ t``, so a lot that lives only inside one second has zero duration.
    Events after ``t1`` are ignored; the full history before ``t0`` is replayed.
    """
    if t1 < t0:
        raise ValueError("t1 must be >= t0")
    clusters = cluster_of or {}
    taints = taint_until or {}
    lots: dict[WalletId, list[LedgerLot]] = defaultdict(list)
    since: dict[WalletId, int] = {}
    out: dict[WalletId, list[Segment]] = defaultdict(list)

    def close(w: WalletId, now: int) -> None:
        a, b = max(since.get(w, t0), t0), min(now, t1)
        if b > a and lots.get(w):
            out[w].append((a, b, tuple(lots[w])))
        since[w] = now

    ordered = sorted(events, key=lambda e: (e.slot, e.sig, e.ix))
    for ev in ordered:
        if ev.ts >= t1:
            break
        for w in {ev.src, ev.dst} - {None}:
            close(w, ev.ts)  # type: ignore[arg-type]
        _apply_event(ev, lots, excluded, clusters, taints)
    for w in sorted(lots):
        close(w, t1)
    return {w: segs for w, segs in sorted(out.items()) if segs}
