"""adapters.epoch_files: deterministic epoch artifacts, offline only."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from adapters.epoch_files import (
    _ClusterScore,
    _EpochResult,
    _EpochState,
    _VestingEntry,
    read_epoch,
    write_epoch,
)
from engine.merkle import MerkleTree, build

W_A = "29d2S7vB453rNYFdR5Ycwt7y9haRT5fwVwL9zTmBhfV2"
W_B = "3JF3sEqM796hk5WFqA6EtmEwJQ9quALszsfJyvXNQKy3"
TREE = build((bytes(32), b"\x01" + bytes(31)))


def _result(**kwargs) -> _EpochResult:
    base = _EpochResult(
        epoch=7,
        payouts={W_B: 2, W_A: 10},
        scores=(
            _ClusterScore(W_B, 2.0, 1.0, 1.0, 1.0, 2.0, 0.2),
            _ClusterScore(W_A, 8.0, 1.0, 1.0, 1.0, 8.0, 0.8),
        ),
        rollover=1,
        dust=0,
        pot=99,
        rail="merkle",
        claims={"root": TREE.root.hex(), "version": 7},
        push=(),
        review=(W_B, W_A),
        inputs_hash="abc123",
        transferred_or_claimable={W_B: 2, W_A: 10},
    )
    return replace(base, **kwargs) if kwargs else base


def _state(**kwargs) -> _EpochState:
    base = _EpochState(
        epoch=8,
        pot=99,
        carry={W_B: 3, W_A: 1},
        forfeit_until={W_A: 1_700_000_000},
        unlocked={W_A: 0.25},
        vesting=(_VestingEntry(W_A, 1_000, 1.5, 1_699_000_000),),
    )
    return replace(base, **kwargs) if kwargs else base


def test_round_trip(tmp_path: Path) -> None:
    dest = write_epoch(tmp_path, _result(), _state(), TREE)
    assert dest == tmp_path / "7"
    result, state, tree = read_epoch(dest)
    assert result.epoch == 7
    assert result.payouts == {W_A: 10, W_B: 2}
    assert result.pot == 99 and result.rollover == 1 and result.dust == 0
    assert result.rail == "merkle"
    assert result.inputs_hash == "abc123"
    assert result.review == (W_A, W_B)
    assert result.scores[0].cluster == W_A
    assert state.epoch == 8 and state.pot == 99
    assert state.carry == {W_A: 1, W_B: 3}
    assert state.vesting[0].vested_amount == 1_000
    assert isinstance(tree, MerkleTree)
    assert tree is not None and tree.root == TREE.root
    assert tree._layers == TREE._layers


def test_balances_json_is_the_running_book(tmp_path: Path) -> None:
    """COIN_MATH §13: earned_total = paid_total + pending, per wallet, Q base units."""
    dest = write_epoch(tmp_path, _result(), _state(paid_total={W_A: 7, "Z" * 32: 5}), TREE)
    book = json.loads((dest / "balances.json").read_text(encoding="utf-8"))
    assert book == {
        W_A: {"earned_total": 8, "paid_total": 7, "pending": 1},
        W_B: {"earned_total": 3, "paid_total": 0, "pending": 3},
        "Z" * 32: {"earned_total": 5, "paid_total": 5, "pending": 0},
    }
    assert list(book) == sorted(book)
    _, state, _ = read_epoch(dest)
    assert state.paid_total == {W_A: 7, "Z" * 32: 5}


def test_byte_identical_on_repeat_and_shuffled_order(tmp_path: Path) -> None:
    a = write_epoch(tmp_path / "a", _result(), _state(), TREE)
    shuffled = _result(
        payouts={W_A: 10, W_B: 2},
        scores=(
            _ClusterScore(W_A, 8.0, 1.0, 1.0, 1.0, 8.0, 0.8),
            _ClusterScore(W_B, 2.0, 1.0, 1.0, 1.0, 2.0, 0.2),
        ),
        review=(W_A, W_B),
        transferred_or_claimable={W_A: 10, W_B: 2},
    )
    b = write_epoch(tmp_path / "b", shuffled, _state(carry={W_A: 1, W_B: 3}), TREE)
    names = ["result.json", "payouts.csv", "tree.json", "state.json", "inputs_hash.txt"]
    for name in names:
        assert (a / name).read_bytes() == (b / name).read_bytes()
    raw = (a / "result.json").read_text(encoding="utf-8")
    assert raw.endswith(chr(10))
    assert '"pot":99' in raw
    csv = (a / "payouts.csv").read_text(encoding="utf-8")
    assert "." not in csv and csv.endswith(chr(10))
    again = write_epoch(tmp_path / "a", _result(), _state(), TREE)
    assert again == a


def test_refuses_overwrite_with_different_content(tmp_path: Path) -> None:
    dest = write_epoch(tmp_path, _result(), _state(), TREE)
    with pytest.raises(FileExistsError, match="different content"):
        write_epoch(tmp_path, _result(pot=100), _state(), TREE)
    assert json.loads((dest / "result.json").read_text())["pot"] == 99


def test_tree_none_and_empty_payouts(tmp_path: Path) -> None:
    dest = write_epoch(
        tmp_path,
        _result(
            payouts={},
            transferred_or_claimable={},
            rail="none",
            claims=None,
            scores=(),
            push=(),
        ),
        _state(carry={}, vesting=(), unlocked={}, forfeit_until={}),
        None,
    )
    result, _state2, tree = read_epoch(dest)
    assert result.payouts == {} and result.claims is None and tree is None
    assert (dest / "tree.json").read_text(encoding="utf-8") == '{"layers":[],"root":null}' + chr(10)
    assert (dest / "payouts.csv").read_text(encoding="utf-8") == "wallet,amount" + chr(10)


def test_money_must_be_int(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="int"):
        write_epoch(tmp_path, _result(pot=99.0), _state(), TREE)  # type: ignore[arg-type]


def test_incomplete_dir_and_hash_mismatch(tmp_path: Path) -> None:
    dest = write_epoch(tmp_path, _result(), _state(), TREE)
    (dest / "inputs_hash.txt").write_text("nope" + chr(10), encoding="utf-8")
    with pytest.raises(ValueError, match="inputs_hash"):
        read_epoch(dest)
    (dest / "inputs_hash.txt").unlink()
    with pytest.raises(FileNotFoundError, match="missing"):
        read_epoch(dest)
