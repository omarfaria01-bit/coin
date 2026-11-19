"""D46 payout inputs (#314): what tools/payout_plan.py needs, from mainnet reads. Never signs.

    HELIUS_API_KEY=... python tools/payout_inputs.py snapshot --config payout-inputs.json
    HELIUS_API_KEY=... python tools/payout_inputs.py export --config payout-inputs.json

`snapshot` (hourly): every holder of our mint into holder_state.json (engine.holder_state:
held_since resets at 0, D47 balance-hours). `export` (daily, after midnight UTC): for the
day that just ended, writes inputs-<day>/{snapshot,balances,exclude}.json in the planner's
formats. Each wallet's `weight` is the day's balance-hours x loyalty (min of two consecutive
snapshots per hour), so buying just before a snapshot earns nothing and holders earn from their
first full hour, launch day included. `export` refuses while the previous plan has transfers not
marked sent in the sender's ledger (the wallet still holds them), and on a day with < 2 snapshots.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.helius_client import HeliusClient  # noqa: E402
from adapters.solana_keys import rewards_excluded  # noqa: E402
from engine.holder_state import HolderState, apply_snapshot, day_inputs  # noqa: E402

CONFIG_KEYS = {"mint", "system_wallet", "excluded", "team_wallets", "fee_bot_ledger", "state_dir"}
REASON = {"dev": "team", "treasury": "system", "program_owned_off_curve": "pool"}
PAGE, MAX_PAGES, MIN_SNAPSHOTS = 1000, 500, 2  # D47: missing hours just earn nothing
Rpc = Callable[[str, object], object]


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text())
    if set(cfg) != CONFIG_KEYS:
        raise ValueError(f"config keys must be exactly {sorted(CONFIG_KEYS)}")
    if not isinstance(cfg["excluded"], dict) or not isinstance(cfg["team_wallets"], list):
        raise ValueError("excluded is {wallet: reason}, team_wallets is a list")
    if set(cfg["excluded"].values()) - {"team", "system", "pool", "burn", "cex"}:
        raise ValueError("excluded reasons: team|system|pool|burn|cex")
    return cfg


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def holders(rpc: Rpc, mint: str) -> dict[str, int]:
    """Owner -> base units over every token account of `mint` (DAS getTokenAccounts)."""
    out: dict[str, int] = {}
    for page in range(1, MAX_PAGES + 1):
        res = rpc("getTokenAccounts", {"mint": mint, "page": page, "limit": PAGE})
        accts = (res or {}).get("token_accounts") or []  # type: ignore[union-attr]
        for a in accts:
            if int(a["amount"]) > 0:
                out[a["owner"]] = out.get(a["owner"], 0) + int(a["amount"])
        if len(accts) < PAGE:
            return out
    raise RuntimeError("too many holder pages")


def excluded(cfg: Mapping, wallets: object) -> dict[str, str]:
    """Wallet -> contract reason. Configured reasons win; then team, system, off-curve pools."""
    auto = rewards_excluded(
        wallets, dev_wallets=cfg["team_wallets"], treasury=[cfg["system_wallet"]]
    )
    return {w: REASON[r] for w, r in auto.items()} | dict(cfg["excluded"])


def snapshot(cfg: Mapping, rpc: Rpc, now: int) -> HolderState:
    path = Path(cfg["state_dir"]) / "holder_state.json"
    state = HolderState.from_json(json.loads(path.read_text())) if path.exists() else HolderState()
    bal = holders(rpc, cfg["mint"])
    excl = excluded(cfg, bal)
    day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    state = apply_snapshot(state, {w: b for w, b in bal.items() if w not in excl}, at=now, day=day)
    _write(path, state.to_json())
    _write(path.parent / "excluded_last.json", excl)  # pools seen in the latest snapshot
    return state


def wallet_balance(rpc: Rpc, owner: str, mint: str) -> int:
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    return sum(
        int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        for a in (res or {}).get("value", [])  # type: ignore[union-attr]
    )


def last_prices(ledger: Path) -> dict[str, Fraction]:
    """Basket mint -> lamports per base unit, from the fee bot's most recent buy of it."""
    prices: dict[str, Fraction] = {}
    for line in ledger.read_text().splitlines() if ledger.exists() else []:
        e = json.loads(line)
        if e.get("event") == "bought" and str(e.get("out", "")).isdigit() and int(e["out"]) > 0:
            prices[e["mint"]] = Fraction(int(e["spent"]), int(e["out"]))
    return prices


def unsent(state_dir: Path, before_day: str) -> list[str]:
    """Memos of the latest plan before `before_day` that the sender's ledger does not show sent."""
    plans = sorted(p for p in state_dir.glob("plan-*.json") if p.stem[5:] < before_day)
    if not plans:
        return []
    led = state_dir / "ledger.jsonl"
    sent = {
        e.get("memo")
        for e in map(json.loads, led.read_text().splitlines() if led.exists() else [])
        if e.get("event") == "transfer" and e.get("status") == "sent"
    }
    return [
        t["memo"] for t in json.loads(plans[-1].read_text())["transfers"] if t["memo"] not in sent
    ]


def export(cfg: Mapping, rpc: Rpc, now: int) -> dict:
    sd = Path(cfg["state_dir"])
    day = (datetime.fromtimestamp(now, UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    missing = unsent(sd, day)
    if missing:
        raise RuntimeError(f"previous plan has {len(missing)} unsent transfers")
    state = HolderState.from_json(json.loads((sd / "holder_state.json").read_text()))
    if state.day != day or state.snapshots_today < MIN_SNAPSHOTS:
        raise RuntimeError(f"{state.snapshots_today} snapshots for {state.day}, need {day}")
    wallets = [
        {
            "address": w,
            "weight": f"{wt.numerator}/{wt.denominator}",
            "balance": str(state.wallets[w].last),
            "holding_seconds": max(0, now - (state.wallets[w].held_since or now)),
        }
        for w, wt in day_inputs(state).items()
    ]
    mints = {
        m: {
            "amount": str(wallet_balance(rpc, cfg["system_wallet"], m)),
            "price_lamports": f"{p.numerator}/{p.denominator}",
        }
        for m, p in sorted(last_prices(Path(cfg["fee_bot_ledger"])).items())
    }
    out = sd / f"inputs-{day}"
    _write(out / "snapshot.json", {"wallets": wallets})
    _write(out / "balances.json", {"system_wallet": cfg["system_wallet"], "mints": mints})
    seen = sd / "excluded_last.json"
    last = json.loads(seen.read_text()) if seen.exists() else {}
    _write(out / "exclude.json", last | excluded(cfg, []))
    return {"day": day, "dir": str(out), "holders": len(wallets), "mints": len(mints)}


def main(argv: list[str] | None = None, rpc: Rpc | None = None, now: int | None = None) -> int:
    ap = argparse.ArgumentParser(description="D46 payout inputs (read-only)")
    ap.add_argument("cmd", choices=("snapshot", "export"))
    ap.add_argument("--config", required=True, type=Path)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if rpc is None:
        key = os.environ.get("HELIUS_API_KEY", "").strip()
        if not key:
            print("HELIUS_API_KEY is not set", file=sys.stderr)
            return 2
        rpc = HeliusClient(key).rpc  # type: ignore[assignment]
    now = int(time.time()) if now is None else now
    if args.cmd == "snapshot":
        s = snapshot(cfg, rpc, now)
        print(json.dumps({"day": s.day, "snapshots": s.snapshots_today, "wallets": len(s.wallets)}))
    else:
        print(json.dumps(export(cfg, rpc, now)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
