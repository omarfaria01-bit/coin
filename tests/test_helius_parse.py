"""Recorded Helius JSON. No network (#161)."""

from __future__ import annotations

from adapters.helius_parse import (
    INCINERATOR,
    JITO_TIP_ACCOUNTS,
    PUMP_PROGRAM,
    excluded_owners,
    normalize_transaction,
    parse_asset,
    parse_largest,
    parse_mint_account,
)
from adapters.market_data import fee_totals

MINT = "Mint111111111111111111111111111111111111111"
TRADER = "Trader1111111111111111111111111111111111111"
TIP = next(iter(JITO_TIP_ACCOUNTS))


def _item() -> dict:
    return {
        "signature": "sig1",
        "parserStatus": "OK",
        "parsed": {
            "slot": 9,
            "blockTime": 1_700_000_000,
            "fee": 2_005_000,
            "feePayer": TRADER,
            "transactionStatus": "OK",
            "nativeTransfers": [
                {"fromUserAccount": TRADER, "toUserAccount": TIP, "amount": 1_000_000},
                {"fromUserAccount": TRADER, "toUserAccount": "not-a-tip", "amount": 50},
            ],
            "tokenTransfers": [
                {
                    "mint": MINT,
                    "fromUserAccount": "curve",
                    "toUserAccount": TRADER,
                    "rawTokenAmount": 10,
                }
            ],
            "summary": {"type": "swap", "description": "ignore this text"},
            "instructions": [
                {
                    "programId": PUMP_PROGRAM,
                    "instructionName": "create",
                    "decoded": {
                        "args": {
                            "name": "Vice City",
                            "symbol": "GTA6",
                            "uri": "https://evil.example/steal",
                        },
                        "accounts": [
                            {"name": "mint", "pubkey": MINT},
                            {"name": "user", "pubkey": TRADER},
                            {"name": "bonding_curve", "pubkey": "curve"},
                        ],
                    },
                }
            ],
        },
    }


def test_normalize_keeps_fee_tip_and_create_and_ignores_uri() -> None:
    tx = normalize_transaction(_item())
    assert tx is not None
    assert tx["fee"] == 2_005_000 and tx["tips"] == 1_000_000
    assert tx["creates"][0]["name"] == "Vice City"  # type: ignore[index]
    assert "uri" not in tx["creates"][0]  # type: ignore[operator]
    got = fee_totals([tx], MINT, window_start=0, window_end=2_000_000_000, truncated=False)
    assert got.lifetime_lamports == 3_005_000
    assert got.traders == frozenset({TRADER})


def test_bad_tip_amount_and_asset_price() -> None:
    item = _item()
    item["parsed"]["nativeTransfers"][0]["amount"] = "nope"
    assert normalize_transaction(item)["tips"] is None  # type: ignore[index]
    asset = parse_asset(
        {
            "content": {
                "metadata": {"name": "GTA", "symbol": "GTA", "description": "Leonida"},
                "json_uri": "https://do-not-fetch.example",
            },
            "token_info": {"price_info": {"price_per_token": 1.5}},
            "creators": [{"address": TRADER}],
        }
    )
    assert asset["price"] == 1.5 and asset["creator"] == TRADER
    assert "json_uri" not in asset


def test_mint_largest_and_excluded_pools() -> None:
    mint = parse_mint_account(
        {
            "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "data": {
                "parsed": {
                    "info": {
                        "supply": "1000",
                        "decimals": 6,
                        "mintAuthority": None,
                        "freezeAuthority": None,
                    }
                }
            },
        }
    )
    assert mint is not None and mint["supply"] == 1000
    rows = parse_largest(
        [{"amount": "10"}, {"amount": "3"}],
        [{"data": {"parsed": {"info": {"owner": "alice"}}}}, None],
    )
    assert rows == [("alice", 10), (None, 3)]
    assert parse_largest([{"amount": "1"}], [None, None]) is None
    skip = excluded_owners(
        hubs={"hub"},
        curves=["curve", None],
        owner_programs={"pda": PUMP_PROGRAM, "wallet": "11111111111111111111111111111111"},
        treasury="treasury",
    )
    assert skip == {INCINERATOR, "hub", "curve", "pda", "treasury"}
