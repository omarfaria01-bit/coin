"""Lot ledger per wallet, LIFO removal (COIN_MATH §1). Owner: Grok."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from engine.types import EventKind, Lot, LotSource, TokenEvent, WalletId


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
