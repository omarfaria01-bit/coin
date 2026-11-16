#!/usr/bin/env python3
"""Devnet epoch dry-run tool: reads holder/transfer data for a test mint on Solana devnet

via public RPC, runs one epoch through engine.epoch.run_epoch, and writes the
payout plan to reports/. Read-only: no transactions, no signing, no keypairs,
refuses any non-devnet cluster URL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.config_loader import load_coin  # noqa: E402
from adapters.hubs import DEFAULT_PATH as DEFAULT_HUBS_PATH  # noqa: E402
from adapters.hubs import load_hubs  # noqa: E402
from adapters.solana_read import (  # noqa: E402
    fetch_mint_history,
    fetch_token_supply,
    validate_devnet_url,
)
from engine.epoch import EpochInputs, empty_state, run_epoch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mint", required=True, help="Test token mint address on Solana devnet")
    p.add_argument(
        "--rpc",
        default="https://api.devnet.solana.com",
        help="Solana devnet RPC URL (must contain 'devnet')",
    )
    p.add_argument("--t0", type=int, required=True, help="Epoch start unix timestamp")
    p.add_argument("--t1", type=int, required=True, help="Epoch end unix timestamp")
    p.add_argument("--pot-inflow", type=int, default=0, help="Pot inflow lamports")
    p.add_argument(
        "--config", type=Path, default=Path("config/coin.json"), help="Path to coin.json"
    )
    p.add_argument("--hubs", type=Path, default=DEFAULT_HUBS_PATH, help="Path to hubs CSV")
    p.add_argument("--out", type=Path, default=Path("reports"), help="Output directory for reports")
    p.add_argument("--limit", type=int, default=1000, help="Max transaction signatures to fetch")
    args = p.parse_args(argv)

    # 1. Validate devnet URL (refuses any non-devnet cluster URL)
    try:
        validate_devnet_url(args.rpc)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Fetching devnet epoch dry run for mint {args.mint} on {args.rpc}...",
        file=sys.stderr,
    )

    # 2. Load config and hubs
    try:
        params = load_coin(args.config)
    except Exception as exc:
        print(f"Error loading coin config: {exc}", file=sys.stderr)
        return 2

    hubs = frozenset(load_hubs(args.hubs)) if args.hubs.exists() else frozenset()

    # 3. Fetch data read-only from devnet RPC
    try:
        total_supply = fetch_token_supply(args.rpc, args.mint)
        events, sol_transfers = fetch_mint_history(args.rpc, args.mint, limit=args.limit)
    except Exception as exc:
        print(f"RPC fetch error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Fetched supply: {total_supply}, events: {len(events)}, "
        f"sol_transfers: {len(sol_transfers)}",
        file=sys.stderr,
    )

    # 4. Construct EpochInputs
    inp = EpochInputs(
        t0=args.t0,
        t1=args.t1,
        slot_range=(0, 0),
        events=events,
        sol_transfers=sol_transfers,
        fundings=(),
        prices=(),
        decimals=6,
        sol_usd=150.0,
        pot_inflow=args.pot_inflow,
        excluded=frozenset(),
        hubs=hubs,
        total_supply=total_supply,
        signers={},
        overrides=(),
        reserves=(),
    )

    # 5. Run epoch
    try:
        result, state = run_epoch(inp, params, empty_state())
    except Exception as exc:
        print(f"Engine run_epoch error: {exc}", file=sys.stderr)
        return 2

    # 6. Write report to reports/
    args.out.mkdir(parents=True, exist_ok=True)
    report_path = args.out / f"devnet_dry_run_{args.mint}.json"
    report_data = {
        "mint": args.mint,
        "rpc_url": args.rpc,
        "epoch": result.epoch,
        "pot": result.pot,
        "rollover": result.rollover,
        "dust": result.dust,
        "rail": result.rail,
        "inputs_hash": result.inputs_hash,
        "payouts": {str(w): amt for w, amt in sorted(result.payouts.items())},
        "push": [[str(w), amt] for w, amt in result.push],
        "scores": [
            {
                "cluster": s.cluster,
                "twab": float(s.twab),
                "hold": float(s.hold),
                "churn": float(s.churn),
                "boost": float(s.boost),
                "score": float(s.score),
                "share": float(s.share),
            }
            for s in result.scores
        ],
    }
    report_path.write_text(json.dumps(report_data, indent=2))
    print(f"Dry run report written to {report_path}", file=sys.stderr)
    print(json.dumps(report_data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
