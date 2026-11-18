"""F8c end-to-end (#205): mint extensions → adapter Metrics → first_failed_filter, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.helius_client import HeliusClient
from adapters.helius_parse import PUMP_PROGRAM
from adapters.index_collect import measure_mints
from adapters.market_data import Sample
from index.filters import Metrics, first_failed_filter
from index.params import IndexParams

MINT = "Mint111111111111111111111111111111111111111"
TRADER = "Trader1111111111111111111111111111111111111"
ALICE = "Alice11111111111111111111111111111111111111"
SYSTEM = "11111111111111111111111111111111"
SPL = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
T22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
START = 1_700_003_600
AS_OF = START + 86_400
P = IndexParams.model_validate(
    json.loads((Path(__file__).resolve().parents[1] / "index" / "params.json").read_text())
)
CREATE = {
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


def _page(i: int) -> dict:
    """One Parsed Events swap by trader i; row 0 also carries the pump.fun create."""
    payer = f"Trader{i:03d}"
    transfer = {
        "mint": MINT,
        "fromUserAccount": "curve",
        "toUserAccount": payer,
        "rawTokenAmount": 1,
    }
    return {
        "signature": f"sig{i}",
        "parserStatus": "OK",
        "parsed": {
            "slot": 9 + i,
            "blockTime": START + 60 * i,
            "fee": 100_000_000,  # 0.1 SOL each; 200 traders clear F4's 10 SOL
            "feePayer": payer,
            "transactionStatus": "OK",
            "nativeTransfers": [],
            "tokenTransfers": [transfer],
            "summary": {"type": "swap"},
            "instructions": [CREATE] if i == 0 else [],
        },
    }


PAGES = [_page(i) for i in range(200)]
SAMPLES = [Sample(MINT, START + 300 * i, 1e6, 60_000.0, 100_000.0, 20.0) for i in range(288)]


def _transport(owner: str, ext: object) -> object:
    info = {"supply": "1000", "decimals": 0, "mintAuthority": None, "freezeAuthority": None}
    if ext is not None:
        info["extensions"] = ext
    asset = {
        "content": {"metadata": {"name": "Vice City", "symbol": "GTA6", "description": "x"}},
        "token_info": {"price_info": {"price_per_token": 2.0}},
        "creators": [{"address": TRADER}],
    }
    alice = {"data": {"parsed": {"info": {"owner": ALICE}}}}
    amount = {"tokenAmount": {"amount": "50"}}
    results = {
        "getAsset": asset,
        "getAccountInfo": {"value": {"owner": owner, "data": {"parsed": {"info": info}}}},
        "getTokenLargestAccounts": {"value": [{"address": "ta1", "amount": "200"}]},
        "getTokenAccountsByOwner": {"value": [{"account": {"data": {"parsed": {"info": amount}}}}]},
    }

    def rpc(method: str, params: object) -> dict:
        if method == "getMultipleAccounts":
            value = [alice if params[0] == ["ta1"] else {"owner": SYSTEM}]
            return {"result": {"value": value}}
        return {"result": results[method]}

    def send(method: str, url: str, body: dict | None) -> tuple[int, object]:
        assert "/search" not in url
        if "dexscreener.com" in url:
            pair = {"baseToken": {"address": MINT}, "liquidity": {"usd": 60_000}}
            return 200, [{**pair, "volume": {"h24": 1_000}, "marketCap": 9}]
        if "transaction-history" in url:
            return 200, {"data": PAGES, "paginationToken": None}
        assert body is not None
        return 200, rpc(str(body["method"]), body["params"])

    return send


def _metrics(owner: str, ext: object = None) -> Metrics:
    client = HeliusClient(
        "unit-test-key",
        _transport(owner, ext),
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        rng=lambda: 0.5,
        rpc_interval=0,
        das_interval=0,
        dex_interval=0,
    )
    return measure_mints(
        client,
        [MINT],
        as_of=AS_OF,
        window_start=START,
        hubs=frozenset(),
        treasury=None,
        samples=SAMPLES,
        fetched_at="2026-11-18T00:00:00Z",
        sample_seconds=300,
        holder_seconds=3600,
    )[0]


@pytest.mark.parametrize(("owner", "ext"), [(SPL, None), (T22, [{"extension": "metadataPointer"}])])
def test_allowlisted_mints_pass_f8(owner: str, ext: object) -> None:
    assert first_failed_filter(_metrics(owner, ext), P) is None


@pytest.mark.parametrize("ext", ["permanentDelegate", "transferHook"])
def test_t22_dangerous_extension_fails_f8(ext: str) -> None:
    assert first_failed_filter(_metrics(T22, [{"extension": ext}]), P) == "F8"


def test_t22_unreadable_extension_is_insufficient_data() -> None:
    m = _metrics(T22, [{"nope": 1}])
    assert m.extensions is None
    assert first_failed_filter(m, P) == "insufficient_data"
