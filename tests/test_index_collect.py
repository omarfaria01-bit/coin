"""Fake-transport observation. No network (#161)."""

from __future__ import annotations

from adapters.helius_client import HeliusClient
from adapters.helius_parse import PUMP_PROGRAM
from adapters.index_collect import measure_mints

MINT = "Mint111111111111111111111111111111111111111"
TRADER = "Trader1111111111111111111111111111111111111"
ALICE = "Alice11111111111111111111111111111111111111"
SYSTEM = "11111111111111111111111111111111"
TIP = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
AS_OF = 1_700_003_600
WHEN = 1_700_000_000


def _page() -> dict:
    create = {
        "programId": PUMP_PROGRAM,
        "instructionName": "create",
        "decoded": {
            "args": {"name": "Vice City", "symbol": "GTA6"},
            "accounts": [
                {"name": "mint", "pubkey": MINT},
                {"name": "user", "pubkey": TRADER},
                {"name": "bonding_curve", "pubkey": "curve"},
            ],
        },
    }
    return {
        "signature": "sig1",
        "parserStatus": "OK",
        "parsed": {
            "slot": 9,
            "blockTime": WHEN,
            "fee": 2_005_000,
            "feePayer": TRADER,
            "transactionStatus": "OK",
            "nativeTransfers": [
                {"fromUserAccount": TRADER, "toUserAccount": TIP, "amount": 1_000_000}
            ],
            "tokenTransfers": [
                {
                    "mint": MINT,
                    "fromUserAccount": "curve",
                    "toUserAccount": TRADER,
                    "rawTokenAmount": 10,
                }
            ],
            "summary": {"type": "swap"},
            "instructions": [create],
        },
    }


def _rpc(method: str, params: object) -> dict:
    if method == "getAsset":
        body = {
            "content": {"metadata": {"name": "Vice City", "symbol": "GTA6", "description": "x"}},
            "token_info": {"price_info": {"price_per_token": 2.0}},
            "creators": [{"address": TRADER}],
        }
    elif method == "getAccountInfo":
        info = {"supply": "1000", "decimals": 0, "mintAuthority": None, "freezeAuthority": None}
        body = {
            "value": {
                "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "data": {"parsed": {"info": info}},
            }
        }
    elif method == "getTokenLargestAccounts":
        body = {"value": [{"address": "ta1", "amount": "200"}]}
    elif method == "getMultipleAccounts":
        who = params[0]  # type: ignore[index]
        row = (
            {"data": {"parsed": {"info": {"owner": ALICE}}}}
            if who == ["ta1"]
            else {"owner": SYSTEM}
        )
        body = {"value": [row]}
    elif method == "getTokenAccountsByOwner":
        body = {
            "value": [
                {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": "50"}}}}}}
            ]
        }
    else:
        raise AssertionError(method)
    return {"result": body}


def _send(method: str, url: str, body: dict | None) -> tuple[int, object]:
    assert "/search" not in url
    if "dexscreener.com" in url:
        pair = {
            "baseToken": {"address": MINT},
            "liquidity": {"usd": 60_000},
            "volume": {"h24": 1_000},
            "marketCap": 9,
        }
        return 200, [pair]
    if "transaction-history" in url:
        return 200, {"data": [_page()], "paginationToken": None}
    assert body is not None
    return 200, _rpc(str(body["method"]), body["params"])


def test_measure_prefers_helius_price_and_sums_fee_plus_tip() -> None:
    client = HeliusClient(
        "unit-test-key",
        _send,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        rng=lambda: 0.5,
        rpc_interval=0,
        das_interval=0,
        dex_interval=0,
    )
    row = measure_mints(
        client,
        [MINT],
        as_of=AS_OF,
        window_start=AS_OF - 86_400,
        hubs=frozenset(),
        treasury=None,
        samples=[],
        fetched_at="2026-11-17T18:00:00Z",
        sample_seconds=300,
        holder_seconds=3600,
    )[0]
    assert row.mc_usd == 2_000.0 and row.liquidity_usd == 60_000.0 and row.volume_usd == 1_000.0
    assert row.total_fees_sol == 0.003005 and row.unique_traders == 1
    assert row.top10_pct == 20.0 and row.dev_pct == 5.0 and row.creator_launches_7d == 1
    # one hour old → 12 five-minute buckets, one spot sample
    assert row.bundle_pct == 0.0 and row.age_hours == 1.0 and row.coverage == 1 / 12
    assert row.mint_authority_revoked is True and row.sources["mc_usd"].startswith("helius-das@")
    assert row.sources["liquidity_usd"].startswith("dexscreener@")


def test_extensions_parse_fail_safe() -> None:
    from adapters.index_collect import _extensions

    assert _extensions({"info": {}}) == []
    assert _extensions({"info": {"extensions": [{"extension": "transferHook"}]}}) == [
        "transferHook"
    ]
    assert _extensions({"info": {"extensions": [{"nope": 1}]}}) is None
    assert _extensions(None) is None
