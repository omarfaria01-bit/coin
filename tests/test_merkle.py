"""Merkle tree must match jup-ag/distributor golden vectors (D7)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import base58
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.merkle import build, claims_document, leaf, verify

_VECTORS = json.loads((Path(__file__).parent / "vectors" / "jup_distributor_v1.json").read_text())


def _b(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)


def _prefixed(inner_hex: str) -> bytes:
    return hashlib.sha256(b"\x00" + _b(inner_hex)).digest()


@pytest.mark.parametrize("case", _VECTORS["sets"], ids=lambda c: c["name"])
def test_vectors_match_upstream_byte_for_byte(case: dict) -> None:
    leaves = [
        leaf(_b(row["claimant"]), row["amount_unlocked"], row["amount_locked"])
        for row in case["claims"]
    ]
    for row, leaf_hash in zip(case["claims"], leaves, strict=True):
        assert leaf_hash == _prefixed(row["inner"])
    tree = build(leaves)
    assert tree.root.hex() == case["root"]
    for i, row in enumerate(case["claims"]):
        proof = tree.proof(i)
        assert [p.hex() for p in proof] == row["proof"]
        assert verify(proof, tree.root, leaves[i]) is True


@pytest.mark.parametrize("case", _VECTORS["sets"], ids=lambda c: c["name"])
def test_tampered_amount_or_proof_fails_verify(case: dict) -> None:
    leaves = [
        leaf(_b(row["claimant"]), row["amount_unlocked"], row["amount_locked"])
        for row in case["claims"]
    ]
    tree = build(leaves)
    row = case["claims"][0]
    bad_leaf = leaf(_b(row["claimant"]), row["amount_unlocked"] + 1, row["amount_locked"])
    proof = tree.proof(0)
    assert verify(proof, tree.root, bad_leaf) is False
    if proof:
        flipped = [bytes([proof[0][0] ^ 1]) + proof[0][1:], *proof[1:]]
        assert verify(flipped, tree.root, leaves[0]) is False
        assert verify(proof, bytes([tree.root[0] ^ 1]) + tree.root[1:], leaves[0]) is False


def test_one_leaf_proof_is_empty() -> None:
    h = leaf(b"\x11" * 32, 1_000_000, 0)
    tree = build([h])
    assert tree.proof(0) == []
    assert verify([], tree.root, h) is True


def test_u64_and_claimant_guards() -> None:
    ok = b"\x01" * 32
    leaf(ok, (1 << 64) - 1, 0)
    leaf(ok, 0, (1 << 64) - 1)
    with pytest.raises(ValueError, match="u64"):
        leaf(ok, 1 << 64, 0)
    with pytest.raises(ValueError, match="u64"):
        leaf(ok, -1, 0)
    with pytest.raises(ValueError, match="32 bytes"):
        leaf(b"\x01" * 31, 1, 0)
    with pytest.raises(ValueError, match="no leaves"):
        build([])
    with pytest.raises(IndexError):
        build([leaf(ok, 1, 0)]).proof(1)


def _wallet(raw: bytes) -> str:
    return base58.b58encode(raw).decode()


def test_claims_document_sorts_drops_zeros_and_sets_locked() -> None:
    a = _wallet(b"\x11" * 32)
    b = _wallet(b"\x22" * 32)
    c = _wallet(b"\x33" * 32)
    # Insert in reverse base58 order plus a zero that must be dropped.
    payouts = {c: 7, b: 0, a: 3}
    doc = claims_document(payouts, version=42)
    assert doc["version"] == 42
    assert [row["claimant"] for row in doc["claims"]] == sorted([a, c])
    assert all(row["amount_locked"] == 0 for row in doc["claims"])
    assert [row["amount_unlocked"] for row in doc["claims"]] == [
        payouts[row["claimant"]] for row in doc["claims"]
    ]
    leaves = [
        leaf(base58.b58decode(row["claimant"]), row["amount_unlocked"], 0) for row in doc["claims"]
    ]
    built = build(leaves)
    assert built.root.hex() == doc["root"]
    for i, row in enumerate(doc["claims"]):
        proof = [_b(p) for p in row["proof"]]
        assert proof == built.proof(i)
        assert verify(proof, built.root, leaves[i]) is True
    with pytest.raises(ValueError, match="positive payout"):
        claims_document({a: 0}, version=1)
    with pytest.raises(ValueError, match="positive payout"):
        claims_document({}, version=1)
    with pytest.raises(ValueError, match="32 bytes"):
        claims_document({"not32": 1}, version=1)
    with pytest.raises(ValueError, match="u64"):
        claims_document({a: 1 << 64}, version=1)


@given(
    st.dictionaries(
        st.binary(min_size=32, max_size=32).map(_wallet),
        st.integers(min_value=0, max_value=10**12),
        min_size=1,
        max_size=16,
    ),
    st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=40, deadline=None)
def test_claims_document_order_independent(payouts: dict[str, int], version: int) -> None:
    if all(v == 0 for v in payouts.values()):
        with pytest.raises(ValueError, match="positive payout"):
            claims_document(payouts, version)
        return
    items = list(payouts.items())
    forward = claims_document(dict(items), version)
    backward = claims_document(dict(reversed(items)), version)
    assert forward == backward
