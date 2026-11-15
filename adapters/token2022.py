"""Token-2022 reward mint: transfer fee, decimals and ATA derivation (offline).

A payout in the reward mint is not what reaches the wallet when the mint has
Token-2022's ``TransferFeeConfig``: ``transfer_checked`` withholds
``min(ceil(amount · bps / 10_000), maximum_fee)``. :func:`plan_payouts` uses the
official ``calculate_pre_fee_amount`` inverse, so the ledger records what the
chain credits and the treasury is funded with the gross.

Inputs are a recorded ``getAccountInfo`` blob (base64) and ints: no RPC, no
signing, no wallet. Layout checked against spl-token-2022 ``main`` 2026-11-15.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import base58

from engine.types import WalletId

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
_TOKEN_PROGRAMS = frozenset({TOKEN_PROGRAM, TOKEN_2022_PROGRAM})
_BPS = 10_000
_U64_MAX = (1 << 64) - 1
_MINT_LEN = 82
_TLV_START = 166  # Account::LEN (165) + account-type byte
_FEE_CONFIG_LEN = 108
_P = (1 << 255) - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_ATA_PUBKEY = base58.b58decode(ATA_PROGRAM)


def _u64(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if not 0 <= value <= _U64_MAX:
        raise ValueError(f"{name} must fit in u64, got {value}")
    return value


def _pubkey(address: str, name: str = "address") -> bytes:
    try:
        raw = base58.b58decode(address)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a base58 pubkey, got {address!r}") from None
    if len(raw) != 32:
        raise ValueError(f"{name} must decode to 32 bytes, got {len(raw)}")
    return raw


@dataclass(frozen=True, slots=True)
class TransferFee:
    """One ``TransferFee`` schedule: first epoch, maximum fee, basis points."""

    epoch: int
    maximum_fee: int
    basis_points: int

    def __post_init__(self) -> None:
        _u64("epoch", self.epoch)
        _u64("maximum_fee", self.maximum_fee)
        if isinstance(self.basis_points, bool) or not 0 <= self.basis_points <= _BPS:
            raise ValueError(f"basis_points must be in [0, {_BPS}], got {self.basis_points}")

    def fee(self, gross: int) -> int:
        """On-chain fee: ceil(gross · bps / 10_000), capped at ``maximum_fee``."""
        _u64("gross", gross)
        if self.basis_points == 0:
            return 0
        return min(-(-gross * self.basis_points // _BPS), self.maximum_fee)

    def pre_fee_amount(self, net: int) -> int:
        """Smallest gross whose post-fee amount is ``net`` (official inverse)."""
        _u64("net", net)
        if self.basis_points == 0:
            return net
        if self.basis_points == _BPS:
            gross = self.maximum_fee + net
        else:
            raw = -(-net * _BPS // (_BPS - self.basis_points))
            gross = net + self.maximum_fee if raw - net >= self.maximum_fee else raw
        if gross > _U64_MAX:
            raise ValueError(f"net {net} needs gross {gross}, which does not fit in u64")
        return gross


@dataclass(frozen=True, slots=True)
class TransferFeeConfig:
    """The two TransferFeeConfig schedules; the chain picks by current epoch."""

    older: TransferFee
    newer: TransferFee

    def for_epoch(self, epoch: int) -> TransferFee:
        return self.newer if epoch >= self.newer.epoch else self.older


@dataclass(frozen=True, slots=True)
class MintAccount:
    address: str
    program_id: str
    decimals: int
    transfer_fee: TransferFeeConfig | None = None


def _account(blob: Mapping[str, Any]) -> tuple[str, bytes]:
    value = blob.get("result", blob)
    value = value.get("value", value) if isinstance(value, Mapping) else None
    if not isinstance(value, Mapping) or not isinstance(value.get("data"), list | str):
        raise ValueError("mint blob has no account data")
    owner, data = value.get("owner"), value["data"]
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, str):
        raise ValueError("account data must be base64 text")
    return str(owner), base64.b64decode(data, validate=True)


def _transfer_fee(raw: bytes) -> TransferFeeConfig:
    if len(raw) != _FEE_CONFIG_LEN:
        raise ValueError(f"TransferFeeConfig must be {_FEE_CONFIG_LEN} bytes, got {len(raw)}")
    older = struct.unpack_from("<QQH", raw, 72)
    newer = struct.unpack_from("<QQH", raw, 90)
    return TransferFeeConfig(TransferFee(*older), TransferFee(*newer))


def _extensions(data: bytes) -> TransferFeeConfig | None:
    if len(data) == _MINT_LEN:
        return None  # mint without extensions
    if len(data) < _TLV_START:
        raise ValueError(f"Token-2022 mint is {len(data)} bytes; expected 82 or >= {_TLV_START}")
    if any(data[_MINT_LEN:165]):
        raise ValueError("non-zero mint padding before the account-type byte")
    if data[165] != 1:
        raise ValueError(f"account type {data[165]} is not a mint (1)")
    found: dict[int, bytes] = {}
    i = _TLV_START
    while i + 4 <= len(data):
        kind, length = struct.unpack_from("<HH", data, i)
        i += 4
        if kind == 0:  # Uninitialized: zero padding starts here
            break
        if i + length > len(data):
            raise ValueError(f"extension {kind} overruns the account data")
        if kind in found:
            raise ValueError(f"duplicate extension {kind}")
        found[kind] = data[i : i + length]
        i += length
    return _transfer_fee(found[1]) if 1 in found else None


def parse_mint_account(blob: Mapping[str, Any], *, address: str) -> MintAccount:
    """Parse a recorded ``getAccountInfo`` value for the mint at ``address``."""
    _pubkey(address, "mint address")
    owner, data = _account(blob)
    if owner not in _TOKEN_PROGRAMS:
        raise ValueError(f"mint owner must be a token program, got {owner!r}")
    if len(data) < _MINT_LEN:
        raise ValueError(f"mint data is {len(data)} bytes, expected >= {_MINT_LEN}")
    if owner == TOKEN_PROGRAM and len(data) != _MINT_LEN:
        raise ValueError("legacy SPL mints are exactly 82 bytes (no extensions)")
    if data[45] != 1:
        raise ValueError("mint is not initialized")
    return MintAccount(
        address, owner, data[44], _extensions(data) if owner != TOKEN_PROGRAM else None
    )


def _is_on_curve(point: bytes) -> bool:
    y = (int.from_bytes(point, "little") & ((1 << 255) - 1)) % _P
    denom = (_D * y * y + 1) % _P
    if denom == 0:
        return False
    x2 = (y * y - 1) * pow(denom, _P - 2, _P) % _P
    return pow(x2, (_P - 1) // 2, _P) in (0, 1)


def associated_token_address(
    owner: WalletId, mint: str, token_program: str = TOKEN_2022_PROGRAM
) -> str:
    """ATA under the mint's token program: ``[owner, token_program, mint]`` PDA."""
    if token_program not in _TOKEN_PROGRAMS:
        raise ValueError(f"unsupported token program {token_program!r}")
    seeds = (
        _pubkey(owner, "owner"),
        _pubkey(token_program, "token program"),
        _pubkey(mint, "mint"),
    )
    for bump in range(255, -1, -1):
        digest = hashlib.sha256(
            b"".join((*seeds, bytes([bump]), _ATA_PUBKEY, b"ProgramDerivedAddress"))
        ).digest()
        if not _is_on_curve(digest):
            return base58.b58encode(digest).decode()
    raise ValueError("no viable ATA bump")  # unreachable in practice


@dataclass(frozen=True, slots=True)
class PayoutLeg:
    """One push payout: ``gross`` leaves the treasury, ``received`` reaches the wallet."""

    wallet: WalletId
    ata: str
    net: int  # owed by the ledger, token base units
    gross: int  # transfer_checked amount
    fee: int
    received: int  # what the chain credits; == net for the official fee math


@dataclass(frozen=True, slots=True)
class PayoutPlan:
    mint: str
    program_id: str
    decimals: int
    epoch: int
    legs: tuple[PayoutLeg, ...]

    def ledger_credits(self) -> dict[WalletId, int]:
        """What the chain credits each wallet; this is what ``record_payment`` takes."""
        return {leg.wallet: leg.received for leg in self.legs}


def plan_payouts(
    payouts: Mapping[WalletId, int],
    mint: MintAccount,
    *,
    epoch: int,
    expected_decimals: int | None = None,
) -> PayoutPlan:
    """Turn owed base-unit amounts (``payouts.csv``) into gross transfers at ``epoch``.

    With a fee extension ``gross > net``: the ledger credits ``received`` and the
    treasury pays the fee.
    """
    _u64("epoch", epoch)
    if expected_decimals is not None and mint.decimals != expected_decimals:
        raise ValueError(
            f"mint {mint.address} has {mint.decimals} decimals, expected {expected_decimals}"
        )
    schedule = mint.transfer_fee.for_epoch(epoch) if mint.transfer_fee else None
    legs: list[PayoutLeg] = []
    for wallet in sorted(payouts):
        _pubkey(wallet, f"payout wallet {wallet!r}")
        net = _u64(f"payout[{wallet}]", payouts[wallet])
        if net == 0:
            raise ValueError(f"payout[{wallet}] must be > 0")
        gross = schedule.pre_fee_amount(net) if schedule else net
        fee = schedule.fee(gross) if schedule else 0
        if gross - fee < net:  # pragma: no cover - the official inverse guarantees this
            raise AssertionError(f"fee math underpaid {wallet}: {gross - fee} < {net}")
        ata = associated_token_address(wallet, mint.address, mint.program_id)
        legs.append(PayoutLeg(wallet, ata, net, gross, fee, gross - fee))
    return PayoutPlan(mint.address, mint.program_id, mint.decimals, epoch, tuple(legs))
