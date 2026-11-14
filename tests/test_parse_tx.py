"""adapters.parse_tx: recorded jsonParsed txs → TokenEvent / SolTransfer (#53)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from adapters.parse_tx import WSOL, ParseError, parse_tx, parse_tx_file
from engine.types import EventKind
from sim.agents import wallet_id

FIX = Path(__file__).resolve().parent / "fixtures" / "parse_tx"
MINT = wallet_id("parse-mint")
ALICE = wallet_id("parse-alice")
BOB = wallet_id("parse-bob")
CAROL = wallet_id("parse-carol")
FEE_AUTH = wallet_id("parse-fee-auth")
# Issue minimum (buy, sell, transfer, multi-ix, failed) plus fee, SOL-only,
# inner-ix buy, and a WSOL-leg buy.
FIXTURES = (
    "buy",
    "buy_inner",
    "buy_wsol",
    "failed",
    "multi_ix",
    "sell",
    "sol_transfer",
    "transfer",
    "transfer_2022_fee",
)


def _load(name: str):
    return parse_tx_file(FIX / f"{name}.json", MINT)


def test_fixtures_present_and_amounts_are_ints() -> None:
    assert [p.stem for p in sorted(FIX.glob("*.json"))] == sorted(FIXTURES)
    for name in FIXTURES:
        events, sols = _load(name)
        for ev in events:
            assert isinstance(ev.amount, int) and ev.amount > 0
            assert ev.lamports is None or isinstance(ev.lamports, int)
        for sol in sols:
            assert isinstance(sol.lamports, int) and sol.lamports > 0


def test_buy_and_inner_buy_are_equivalent() -> None:
    events, sols = _load("buy")
    assert len(events) == 1
    ev = events[0]
    assert ev.kind is EventKind.BUY and ev.src is None and ev.dst == ALICE
    assert ev.amount == 1_000_000_000 and ev.lamports == 1_000_000_000
    assert ev.fee_payer == ALICE and ev.ix == 1
    assert len(sols) == 1 and sols[0].src == ALICE and sols[0].lamports == 1_000_000_000
    inner, inner_sols = _load("buy_inner")
    assert [e.kind for e in inner] == [EventKind.BUY]
    assert inner[0].dst == ALICE
    assert inner[0].amount == ev.amount and inner[0].lamports == ev.lamports
    assert inner[0].ix == 2  # parent 0, second inner ix (0*1000+2)
    assert inner_sols[0].lamports == 1_000_000_000


def test_sell() -> None:
    events, sols = _load("sell")
    assert len(events) == 1
    ev = events[0]
    assert ev.kind is EventKind.SELL and ev.src == ALICE and ev.dst is None
    assert ev.amount == 1_000_000_000 and ev.lamports == 1_000_000_000
    assert sols[0].dst == ALICE and sols[0].lamports == 1_000_000_000


def test_transfer() -> None:
    events, sols = _load("transfer")
    assert len(events) == 1
    ev = events[0]
    assert ev.kind is EventKind.TRANSFER and ev.src == ALICE and ev.dst == BOB
    assert ev.amount == 500_000_000 and ev.lamports is None
    assert sols == ()


def test_token_2022_fee_splits_received_and_withheld() -> None:
    events, _sols = _load("transfer_2022_fee")
    kinds = [(e.kind, e.src, e.dst, e.amount) for e in events]
    assert kinds == [
        (EventKind.TRANSFER, ALICE, BOB, 990_000),
        (EventKind.TRANSFER, ALICE, FEE_AUTH, 10_000),
    ]
    assert all(e.lamports is None for e in events)


def test_multi_ix_emits_two_transfers_in_ix_order() -> None:
    events, _sols = _load("multi_ix")
    assert [e.ix for e in events] == [0, 1]
    assert events[0].src == ALICE and events[0].dst == BOB and events[0].amount == 100_000_000
    assert events[1].src == BOB and events[1].dst == CAROL and events[1].amount == 40_000_000


def test_failed_tx_emits_nothing() -> None:
    assert _load("failed") == ((), ())


def test_sol_transfer_only() -> None:
    events, sols = _load("sol_transfer")
    assert events == ()
    assert len(sols) == 1 and sols[0].src == ALICE and sols[0].dst == BOB
    assert sols[0].lamports == 42_000_000


def _blank_tx(signatures: list | None = None) -> dict:
    sigs = ["s"] if signatures is None else signatures
    return {
        "slot": 1,
        "blockTime": 1,
        "meta": {
            "err": None,
            "fee": 0,
            "preBalances": [0],
            "postBalances": [0],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
        "transaction": {
            "signatures": sigs,
            "message": {"accountKeys": ["A"], "instructions": []},
        },
    }


def test_buy_wsol_uses_wrapped_sol_delta_and_adds_back_tx_fee() -> None:
    assert len(WSOL) == 43
    assert WSOL == "So11111111111111111111111111111111111111112"
    events, sols = _load("buy_wsol")
    assert sols == ()  # payment is WSOL, not a native system transfer
    assert len(events) == 1
    ev = events[0]
    assert ev.kind is EventKind.BUY and ev.dst == ALICE and ev.src is None
    assert ev.amount == 1_000_000_000
    # Native SOL drops only by the 5000 tx fee; that fee is added back, so
    # lamports is the 1 SOL WSOL payment, not 1_000_005_000.
    assert ev.lamports == 1_000_000_000


def test_token_2022_fee_ix_does_not_collide_and_sink_falls_back_to_mint() -> None:
    events, _ = _load("transfer_2022_fee")
    assert events[0].ix + 1_000_000 == events[1].ix
    raw = json.loads((FIX / "transfer_2022_fee.json").read_text(encoding="utf-8"))

    # Drop the visible fee account so the withheld sink is the mint.
    def _drop_fee_acc(rows: list) -> list:
        return [r for r in rows if r["accountIndex"] != 4]

    raw["meta"]["preTokenBalances"] = _drop_fee_acc(raw["meta"]["preTokenBalances"])
    raw["meta"]["postTokenBalances"] = _drop_fee_acc(raw["meta"]["postTokenBalances"])
    evs, _ = parse_tx(raw, MINT)
    assert [(e.dst, e.amount) for e in evs] == [(BOB, 990_000), (MINT, 10_000)]


def test_failed_tx_with_short_balances_is_empty() -> None:
    raw = json.loads((FIX / "failed.json").read_text(encoding="utf-8"))
    raw["meta"]["preBalances"] = []
    raw["meta"]["postBalances"] = []
    assert parse_tx(raw, MINT) == ((), ())


@pytest.mark.parametrize(
    ("blob", "needle"),
    [
        ({}, "meta must be an object"),
        (_blank_tx(signatures=[]), "no signatures"),
        ({"jsonrpc": "2.0", "result": None}, "result is null"),
        (_blank_tx(), None),  # valid empty tx
    ],
)
def test_malformed_or_empty(blob: dict, needle: str | None) -> None:
    if needle is None:
        assert parse_tx(blob, MINT) == ((), ())
        return
    with pytest.raises(ParseError, match=needle):
        parse_tx(blob, MINT)


def test_rejects_float_amounts_and_missing_mint() -> None:
    raw = json.loads((FIX / "transfer.json").read_text(encoding="utf-8"))
    raw["meta"]["preTokenBalances"][0]["uiTokenAmount"]["amount"] = 1.5
    with pytest.raises(ParseError, match="must be an int"):
        parse_tx(raw, MINT)
    with pytest.raises(ParseError, match="mint is required"):
        parse_tx(raw, "")


def test_unparsed_mint_movement_is_rejected() -> None:
    raw = json.loads((FIX / "transfer.json").read_text(encoding="utf-8"))
    raw["transaction"]["message"]["instructions"] = []
    with pytest.raises(ParseError, match="no parsed token transfer"):
        parse_tx(raw, MINT)


def test_module_has_no_network_imports() -> None:
    tree = ast.parse((Path(__file__).resolve().parents[1] / "adapters" / "parse_tx.py").read_text())
    banned = {
        "urllib",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "solana",
        "solders",
        "socket",
        "ssl",
    }
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(n.name.split(".")[0] for n in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not (names & banned), names & banned
