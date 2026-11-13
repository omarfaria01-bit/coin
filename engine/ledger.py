"""Lot ledger per wallet, LIFO removal (COIN_MATH §1). Owner: Claude."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from engine.types import Lot, TokenEvent, WalletId


def build_lots(
    events: Sequence[TokenEvent],
    excluded: frozenset[WalletId],
    twap_1h: Callable[[int], float],
) -> Mapping[WalletId, tuple[Lot, ...]]:
    """Replay events in (slot, sig, ix) order and return each wallet's lots at the end.

    BUY adds a POOL_BUY lot at the executed price; TRANSFER in adds a TRANSFER_IN lot at
    twap_1h(ts); SELL and TRANSFER out remove lots LIFO. Excluded accounts hold no lots.
    """
    raise NotImplementedError
