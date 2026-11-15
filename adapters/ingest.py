"""Strict validation for every file the engine ingests (events, prices, balances) — #138.

Pydantic owns the types (`extra="forbid"`, strict ints reject bools/floats/strings) and the
`BalanceRow` invariant; the annotated validators add the cross-row sanity rules. Amounts are
ints only, never float; prices keep the pre-existing `engine.types.PricePoint` float interface.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Protocol

import base58
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    field_validator,
    model_validator,
)


class IngestError(ValueError):
    """Rejected input file; the message names the file and every bad field."""


class EventLike(Protocol):
    """The fields the event sanity rules need (satisfied by tools.run_epoch.EventIn)."""

    slot: int
    ts: int
    sig: str
    ix: int
    mint: str | None


class TimedLike(Protocol):
    ts: int


def solana_id(name: str, value: str) -> str:
    """A Solana id (mint or wallet): non-empty base58 decoding to exactly 32 bytes."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty base58 string")
    try:
        size = len(base58.b58decode(value))
    except (TypeError, ValueError):
        raise ValueError(f"{name} is not valid base58: {value!r}") from None
    if size != 32:
        raise ValueError(f"{name} must decode to 32 bytes, got {size}")
    return value


def check_events(rows: Sequence[EventLike]) -> list[EventLike]:
    """History in chain order: ``(slot, ts)`` non-decreasing, unique ``(sig, ix)``, one slot
    per tx sig. Runs at the boundary, before the engine sorts, so the row index is in the error.
    """
    seen: dict[tuple[str, int], int] = {}
    sig_slot: dict[str, int] = {}
    prev: EventLike | None = None
    for i, row in enumerate(rows):
        key = (row.sig, row.ix)
        if key in seen:
            raise ValueError(f"events[{i}]: duplicate event (sig={row.sig}, ix={row.ix})")
        first_slot = sig_slot.setdefault(row.sig, row.slot)
        if first_slot != row.slot:
            raise ValueError(
                f"events[{i}]: duplicate tx sig {row.sig} at slots {first_slot} and {row.slot}"
            )
        if prev is not None:
            if row.slot < prev.slot:
                raise ValueError(
                    f"events[{i}].slot must be non-decreasing: {row.slot} after {prev.slot}"
                )
            if row.ts < prev.ts:
                raise ValueError(f"events[{i}].ts must be non-decreasing: {row.ts} after {prev.ts}")
            if row.slot == prev.slot and row.ts != prev.ts:
                raise ValueError(
                    f"events[{i}].ts={row.ts} differs from events[{i - 1}].ts={prev.ts} "
                    "in the same slot"
                )
        seen[key] = row.slot
        prev = row
    return list(rows)


def check_prices(rows: Sequence[TimedLike]) -> list[TimedLike]:
    """A price series has one strictly increasing timestamp per point (no gaps/duplicates)."""
    prev: TimedLike | None = None
    for i, row in enumerate(rows):
        if prev is not None and row.ts <= prev.ts:
            raise ValueError(
                f"prices[{i}].ts must be strictly increasing: {row.ts} after {prev.ts}"
            )
        prev = row
    return list(rows)


def check_known_mints(rows: Sequence[EventLike], known_mints: Collection[str]) -> None:
    """Every event that names a mint must name one from the configured allowlist."""
    known = set(known_mints)
    for i, row in enumerate(rows):
        if row.mint is None:
            continue
        if not known:
            raise ValueError(
                f"events[{i}]: mint {row.mint} declared but no known mints are configured"
            )
        if row.mint not in known:
            raise ValueError(
                f"events[{i}]: unknown mint {row.mint}; known: {', '.join(sorted(known))}"
            )


class BalanceRow(BaseModel):
    """One wallet's COIN_MATH §13 running book, in Q base units."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    earned_total: int = Field(ge=0)
    paid_total: int = Field(ge=0)
    pending: int = Field(ge=0)

    @model_validator(mode="after")
    def _adds_up(self) -> BalanceRow:
        if self.earned_total != self.paid_total + self.pending:
            raise ValueError("earned_total must equal paid_total + pending")
        return self


class BalancesIn(RootModel[dict[str, BalanceRow]]):
    """`balances.json` as written by adapters.epoch_files: wallet -> running book."""

    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def _wallets(cls, book: dict[str, BalanceRow]) -> dict[str, BalanceRow]:
        if any(not wallet for wallet in book):
            raise ValueError("wallet id must be non-empty")
        return book


def format_validation_error(where: Path, exc: ValidationError) -> str:
    """One line for the file, then one `loc: message` line per rejected field."""
    lines = [f"{where}: {exc.error_count()} validation error(s)"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def load_balances(path: Path) -> dict[str, BalanceRow]:
    """Parse and validate `balances.json`; raise `IngestError` with every bad field named."""
    source = Path(path)
    try:
        return BalancesIn.model_validate_json(source.read_bytes()).root
    except ValidationError as exc:
        raise IngestError(format_validation_error(source, exc)) from None
