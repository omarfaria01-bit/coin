"""Read-only Solana RPC adapter: fetches history and normalizes it into engine.types.

Mainnet READS only or Devnet read-only dry runs. Never sign or send transactions from this module.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from adapters.parse_tx import parse_tx
from engine.types import SolTransfer, TokenEvent


def validate_devnet_url(url: str) -> str:
    """Refuse any non-devnet cluster URL. Must contain 'devnet' case-insensitively."""
    if not isinstance(url, str) or "devnet" not in url.lower():
        raise ValueError(f"Refusing non-devnet cluster URL: {url!r} (must contain 'devnet')")
    return url


def rpc_call(url: str, method: str, params: list[Any], timeout: float = 30.0) -> Any:
    """Make a read-only JSON-RPC call to Solana devnet."""
    validate_devnet_url(url)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "coin-devnet-dry-run/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"RPC error on {method}: {exc}") from exc

    if payload.get("error"):
        raise RuntimeError(f"RPC error response on {method}: {payload['error']}")
    return payload.get("result")


def fetch_token_supply(rpc_url: str, mint: str) -> int:
    """Fetch total token supply for mint via getTokenSupply."""
    res = rpc_call(rpc_url, "getTokenSupply", [mint])
    if not isinstance(res, dict) or "value" not in res:
        raise RuntimeError(f"Unexpected getTokenSupply result for mint {mint}: {res}")
    val = res["value"]
    amount_str = val.get("amount") if isinstance(val, dict) else None
    if amount_str is None:
        raise RuntimeError(f"getTokenSupply missing amount for mint {mint}: {val}")
    return int(amount_str)


def fetch_signatures(rpc_url: str, mint: str, limit: int = 1000) -> list[str]:
    """Fetch transaction signatures associated with mint address."""
    res = rpc_call(rpc_url, "getSignaturesForAddress", [mint, {"limit": limit}])
    if not isinstance(res, list):
        return []
    sigs = []
    for item in res:
        if isinstance(item, dict) and "signature" in item:
            sigs.append(str(item["signature"]))
    return sigs


def fetch_transaction(rpc_url: str, signature: str) -> dict[str, Any] | None:
    """Fetch parsed transaction details via getTransaction with jsonParsed encoding."""
    res = rpc_call(
        rpc_url,
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            },
        ],
    )
    if not isinstance(res, dict):
        return None
    return res


def fetch_mint_history(
    rpc_url: str, mint: str, limit: int = 1000
) -> tuple[tuple[TokenEvent, ...], tuple[SolTransfer, ...]]:
    """Fetch signatures and transactions for mint, parsing them into TokenEvent and SolTransfer."""
    sigs = fetch_signatures(rpc_url, mint, limit=limit)
    events_list: list[TokenEvent] = []
    sols_list: list[SolTransfer] = []
    for sig in sigs:
        tx_data = fetch_transaction(rpc_url, sig)
        if not tx_data:
            continue
        try:
            evs, sols = parse_tx(tx_data, mint)
            events_list.extend(evs)
            sols_list.extend(sols)
        except Exception:
            # Skip unparseable or failed transactions
            continue
    return tuple(events_list), tuple(sols_list)
