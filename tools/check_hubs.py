#!/usr/bin/env python3
"""Read-only mainnet check that each hubs allowlist address exists.

Uses getMultipleAccounts (same info as getAccountInfo). Never signs or sends a
transaction. Public RPC, rate-limited. Not run in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.hubs import DEFAULT_PATH, load_hubs  # noqa: E402
from adapters.market_data_legacy import require_https  # noqa: E402

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
BATCH = 50
PAUSE_S = 0.4


def _rpc(url: str, method: str, params: list, timeout: float) -> dict:
    require_https(url)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "coin-check-hubs/1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload["result"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=DEFAULT_PATH)
    p.add_argument("--rpc", default=DEFAULT_RPC, help="Read-only mainnet RPC")
    p.add_argument("--pause", type=float, default=PAUSE_S, help="Seconds between RPC batches")
    p.add_argument("--timeout", type=float, default=30.0)
    args = p.parse_args(argv)
    try:
        require_https(args.rpc)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    hubs = sorted(load_hubs(args.csv))
    print(f"checking {len(hubs)} hubs on {args.rpc}", file=sys.stderr)
    missing: list[str] = []
    found = 0
    for i in range(0, len(hubs), BATCH):
        batch = hubs[i : i + BATCH]
        try:
            result = _rpc(
                args.rpc,
                "getMultipleAccounts",
                [batch, {"encoding": "base64", "commitment": "finalized"}],
                args.timeout,
            )
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"RPC error on batch starting {batch[0]}: {exc}", file=sys.stderr)
            return 2
        values = result.get("value") if isinstance(result, dict) else result
        if not isinstance(values, list) or len(values) != len(batch):
            print("unexpected RPC result shape", file=sys.stderr)
            return 2
        for addr, info in zip(batch, values, strict=True):
            if info is None:
                missing.append(addr)
                print(f"MISSING {addr}")
            else:
                found += 1
                owner = info.get("owner", "?") if isinstance(info, dict) else "?"
                print(f"ok {addr} owner={owner}")
        if i + BATCH < len(hubs):
            time.sleep(args.pause)
    print(f"found={found} missing={len(missing)} total={len(hubs)}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
