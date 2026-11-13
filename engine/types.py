"""Core data types shared by every engine module. See docs/ENGINE_DESIGN.md §2.

Units: token amounts are ints in base units; SOL amounts are ints in lamports; time is int
unix seconds (taken from on-chain block time, never the wall clock); prices are float SOL per
whole token. Wallet and cluster ids are base58 strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

WalletId = str
ClusterId = str  # = lexicographically smallest WalletId in the cluster


class LotSource(StrEnum):
    POOL_BUY = "pool_buy"
    TRANSFER_IN = "transfer_in"


class EventKind(StrEnum):
    BUY = "buy"  # pool/curve -> wallet (also via aggregators)
    SELL = "sell"  # wallet -> pool/curve
    TRANSFER = "transfer"  # wallet -> wallet


@dataclass(frozen=True, slots=True)
class TokenEvent:
    """One movement of the project token, normalized by adapters/solana_read.py."""

    slot: int
    ts: int
    sig: str
    ix: int  # instruction index inside the tx; (slot, sig, ix) orders events deterministically
    kind: EventKind
    src: WalletId | None  # None for BUY
    dst: WalletId | None  # None for SELL
    amount: int  # token base units, > 0
    lamports: int | None  # SOL paid (BUY) or received (SELL), fees included; None for TRANSFER
    fee_payer: WalletId


@dataclass(frozen=True, slots=True)
class SolTransfer:
    """A native SOL transfer between two wallets (sybil evidence, §7)."""

    slot: int
    ts: int
    sig: str
    src: WalletId
    dst: WalletId
    lamports: int


@dataclass(frozen=True, slots=True)
class FirstFunding:
    """The first SOL inflow a wallet ever received (sybil evidence, §7)."""

    wallet: WalletId
    funder: WalletId
    ts: int
    created_ts: int  # first on-chain activity of `wallet`


@dataclass(frozen=True, slots=True)
class Lot:
    amount: int
    cost_lamports_per_token: float  # executed price (fees incl.) or 1h TWAP for transfers
    t_acquired: int
    source: LotSource


@dataclass(frozen=True, slots=True)
class PricePoint:
    ts: int
    price: float  # SOL per whole token
