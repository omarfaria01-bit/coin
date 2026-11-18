#!/usr/bin/env python3
"""Anyone can re-check an hourly draw from public data (D39, audit #271 M1). Offline, read-only.

Input: the draw record JSON published by the job:
  {"commit": <canonical inputs JSON, published before the VRF>,
   "snapshot_hash": hex (the value committed on-chain),
   "rho": hex | null (ORAO fulfilled randomness for seed = snapshot_hash),
   "vrf_requests": int,
   "claimed": {"winners": [...], "prizes": {group: "lamports"}, "rollover": "lamports"}}

Exit 0 and print the wallet payouts when everything reproduces; exit 1 on any mismatch.
The payout sender must run the same check (`engine.payout_guard.verified_draw_payouts`).

    uv run python tools/draw_verify.py draw-000123.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.draw_commit import (  # noqa: E402
    DrawMismatch,
    inputs_from_public,
    snapshot_hash,
    verify_draw,
    wallet_prizes,
)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    rec = json.loads(Path(argv[1]).read_text())
    inputs = inputs_from_public(rec["commit"])
    committed = bytes.fromhex(rec["snapshot_hash"])
    rho = bytes.fromhex(rec["rho"]) if rec.get("rho") else None
    claimed = rec["claimed"]
    try:
        plan = verify_draw(
            inputs,
            committed,
            rho,
            vrf_requests=int(rec["vrf_requests"]),
            claimed_winners=claimed["winners"],
            claimed_prizes={k: int(v) for k, v in claimed["prizes"].items()},
            claimed_rollover=int(claimed["rollover"]),
        )
    except DrawMismatch as e:
        print(f"MISMATCH: {e}", file=sys.stderr)
        return 1
    out = {
        "snapshot_hash": snapshot_hash(inputs).hex(),
        "drawn": plan.drawn,
        "reason": plan.reason,
        "eligible_groups": plan.eligible,
        "winners": list(plan.winners),
        "wallet_payouts": {w: str(v) for w, v in wallet_prizes(inputs, plan).items()},
        "rollover": str(plan.rollover),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
