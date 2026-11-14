"""One clock: event ordering, the block-time seconds clock, canonical JSON (COIN_MATH §0).

Exact int arithmetic only: no `math` import, no float literals (payout path, COIN_MATH §0).
Inputs are assumed to come from **finalized** slots only; this module does no RPC and cannot
verify finality itself, so that precondition is on the caller (`adapters/`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable


@runtime_checkable
class OrderedEvent(Protocol):
    """Anything placeable in the COIN_MATH §0 event order: (slot, tx index, ix index)."""

    slot: int
    tx_index: int
    ix_index: int


_E = TypeVar("_E", bound=OrderedEvent)


def event_order_key(event: OrderedEvent) -> tuple[int, int, int]:
    """(slot, tx index, ix index) — the COIN_MATH §0 deterministic event order."""
    return (event.slot, event.tx_index, event.ix_index)


def sort_events(events: Iterable[_E]) -> tuple[_E, ...]:
    """Events in COIN_MATH §0 order: (slot, tx index, ix index)."""
    return tuple(sorted(events, key=event_order_key))


@dataclass(frozen=True, slots=True)
class SlotTime:
    """One finalized slot's observed block time; `block_time` is `None` when the RPC omitted it."""

    slot: int
    block_time: int | None


def clamp_block_times(slot_times: Sequence[SlotTime]) -> dict[int, int]:
    """The block-time seconds clock (COIN_MATH §0 "One clock").

    `slot_times` must already be strictly increasing, finalized slots (ascending `slot`). A
    slot's effective time is its own block time, or the previous slot's effective time if its
    own is missing or lower than that — the clock never moves backward. The first slot in the
    sequence must carry a block time (there is no earlier slot to clamp from).
    """
    out: dict[int, int] = {}
    prev_slot: int | None = None
    prev_ts: int | None = None
    for st in slot_times:
        if prev_slot is not None and st.slot <= prev_slot:
            raise ValueError(f"slots must be strictly increasing: {st.slot} after {prev_slot}")
        if st.block_time is None or (prev_ts is not None and st.block_time < prev_ts):
            if prev_ts is None:
                raise ValueError(
                    f"slot {st.slot} has no block time and no earlier slot to clamp from"
                )
            effective = prev_ts
        else:
            effective = st.block_time
        out[st.slot] = effective
        prev_slot, prev_ts = st.slot, effective
    return out


def canonical_json(value: Any) -> bytes:
    """COIN_MATH §0 "Serialization": sorted keys, no insignificant whitespace, UTF-8, ints as
    decimal strings. `bool` stays a JSON boolean; `float` is rejected (exact arithmetic only).
    """
    text = json.dumps(
        _stringify_ints(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return text.encode("utf-8")


def sha256_hex(value: Any) -> str:
    """SHA-256 of `canonical_json(value)`, hex-encoded (COIN_MATH §0 "Serialization")."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _stringify_ints(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Mapping):
        bad_keys = [k for k in value if not isinstance(k, str)]
        if bad_keys:
            raise TypeError(f"canonical_json requires string keys, got {bad_keys[0]!r}")
        return {k: _stringify_ints(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_stringify_ints(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, str):
        return value
    # Anything else (notably float) is rejected: exact arithmetic only (§0).
    raise TypeError(
        f"canonical_json cannot serialize {type(value).__name__} "
        "(no float: use int or fractions.Fraction)"
    )
