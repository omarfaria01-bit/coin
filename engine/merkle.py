"""Merkle claims tree matching jup-ag/distributor (D7 / COIN_MATH §13). Owner: Grok."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import base58

from engine.types import WalletId

_U64_MAX = (1 << 64) - 1
_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"


def _sha256(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.digest()


def _u64_le(n: int) -> bytes:
    if n < 0 or n > _U64_MAX:
        raise ValueError(f"amount does not fit in u64: {n}")
    return n.to_bytes(8, "little")


def _inner(claimant: bytes, amount_unlocked: int, amount_locked: int) -> bytes:
    if len(claimant) != 32:
        raise ValueError(f"claimant must be 32 bytes, got {len(claimant)}")
    return _sha256(claimant, _u64_le(amount_unlocked), _u64_le(amount_locked))


def leaf(claimant: bytes, amount_unlocked: int, amount_locked: int) -> bytes:
    """Prefixed merkle leaf: sha256(0x00 || sha256(claimant || unlocked_le || locked_le))."""
    return _sha256(_LEAF_PREFIX, _inner(claimant, amount_unlocked, amount_locked))


def _parent(left: bytes, right: bytes) -> bytes:
    # On-chain verify and tree build both sort the two 32-byte siblings before hashing.
    lo, hi = (left, right) if left <= right else (right, left)
    return _sha256(_NODE_PREFIX, lo, hi)


@dataclass(frozen=True, slots=True)
class MerkleTree:
    root: bytes
    _layers: tuple[tuple[bytes, ...], ...]

    def proof(self, i: int) -> list[bytes]:
        if i < 0 or i >= len(self._layers[0]):
            raise IndexError(i)
        out: list[bytes] = []
        idx = i
        for layer in self._layers[:-1]:
            if idx % 2 == 0:
                sib = layer[idx + 1] if idx + 1 < len(layer) else layer[idx]
            else:
                sib = layer[idx - 1]
            out.append(sib)
            idx //= 2
        return out


def build(leaves: Sequence[bytes]) -> MerkleTree:
    """Build from already-prefixed 32-byte leaves. Odd levels duplicate the last node."""
    if not leaves:
        raise ValueError("cannot build a merkle tree with no leaves")
    layer = [bytes(item) for item in leaves]
    layers: list[tuple[bytes, ...]] = [tuple(layer)]
    while len(layer) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(layer), 2):
            right = layer[i + 1] if i + 1 < len(layer) else layer[i]
            nxt.append(_parent(layer[i], right))
        layer = nxt
        layers.append(tuple(layer))
    return MerkleTree(root=layer[0], _layers=tuple(layers))


def verify(proof: Sequence[bytes], root: bytes, leaf_hash: bytes) -> bool:
    """Mirror jito-merkle-verify: sort each (current, sibling) pair, prefix 0x01."""
    computed = bytes(leaf_hash)
    for sibling in proof:
        computed = _parent(computed, bytes(sibling))
    return computed == bytes(root)


def claims_document(payouts: Mapping[WalletId, int], version: int) -> dict:
    """JSON-ready claims doc; claimants sorted, zero amounts dropped, locked = 0."""
    rows: list[tuple[bytes, str, int]] = []
    for wallet, amount in payouts.items():
        if amount == 0:
            continue
        raw = base58.b58decode(wallet)
        if len(raw) != 32:
            raise ValueError(f"claimant must decode to 32 bytes: {wallet}")
        _u64_le(amount)  # overflow check
        rows.append((raw, wallet, amount))
    rows.sort(key=lambda row: row[1])
    if not rows:
        raise ValueError("claims_document requires at least one positive payout")
    leaves = [leaf(raw, amount, 0) for raw, _wallet, amount in rows]
    tree = build(leaves)
    claims = []
    for i, (_raw, wallet, amount) in enumerate(rows):
        claims.append(
            {
                "claimant": wallet,
                "amount_unlocked": amount,
                "amount_locked": 0,
                "proof": [p.hex() for p in tree.proof(i)],
            }
        )
    return {"version": version, "root": tree.root.hex(), "claims": claims}
