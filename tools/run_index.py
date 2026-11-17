#!/usr/bin/env python3
"""Collect market data and compute one GTA 6 index rebalance (issue #161).

    uv run python tools/run_index.py --as-of 2026-11-18T18:00:00Z --out index/out
    uv run python tools/run_index.py --as-of 2026-11-18T18:00:00Z --out index/out --offline

Read-only: DexScreener, Solana JSON-RPC (`SOLANA_RPC_URL`) and, when `HELIUS_API_KEY` is set,
Helius Parsed Events. Keys are read from the environment and never printed or stored. Samples
are appended to `data/index/samples/<date>.jsonl` (gitignored); the output is canonical JSON.
F4 (total fees) is not wired yet, so dry runs skip it (INDEX_RULES §3, issue #161 step 6).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters import market_data  # noqa: E402
from index.filters import MISSING  # noqa: E402
from index.params import DryRun, IndexParams, Overrides, frac  # noqa: E402
from index.select import canonical_json, run_index  # noqa: E402

SAMPLES = ROOT / "data" / "index" / "samples"
PARAMS = ROOT / "index" / "params.json"
OVERRIDES = ROOT / "index" / "overrides.json"


class OfficialRefusal(RuntimeError):
    """An official run was refused; nothing is written and the previous file stays."""


def parse_iso(text: str) -> int:
    """ISO-8601 timestamp, timezone-aware (a bare date means 00:00 UTC)."""
    value = text.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"bad --as-of {text!r}: {exc}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def previous_members(out_dir: Path, current: str) -> list[str]:
    """Members of the newest output file older than `current` (INDEX_RULES §5)."""
    candidates = sorted(p for p in out_dir.glob("*.json") if p.name < current)
    for path in reversed(candidates):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        members = data.get("members") if isinstance(data, dict) else None
        if isinstance(members, list):
            return [m["mint"] for m in members if isinstance(m, dict) and "mint" in m]
    return []


def _passes_cheap_filters(m: Any, params: IndexParams) -> bool:
    """F1 and F2 only: the Helius steps run for these coins (kiwi, 18 Nov)."""
    return (
        m.age_hours is not None
        and m.age_hours >= float(frac(params.filters.min_age_hours))
        and m.liquidity_usd is not None
        and m.liquidity_usd >= float(frac(params.filters.min_liquidity_usd))
    )


def collect(
    samples_path: Path,
    as_of: int,
    params: IndexParams,
    overrides: Overrides,
    *,
    rpc_url: str | None,
    helius_key: str | None,
    holders: bool,
    fetch: market_data.Opener = market_data.get_json,
    poster: market_data.Poster = market_data.post_json,
) -> int:
    """Discover, sample and enrich; append JSONL records. Returns records written."""
    existing = market_data.read_samples(str(samples_path))
    known_launch = {r["mint"] for r in existing if r.get("kind") == "launch"}
    last_hourly: dict[str, int] = {}
    for rec in existing:
        if rec.get("kind") in {"holders", "flow"}:
            last_hourly[rec["mint"]] = max(last_hourly.get(rec["mint"], 0), int(rec["ts"]))
    hourly_due = params.holder_sample_minutes * 60
    pairs = market_data.discover(params, overrides, opener=fetch)
    if not pairs:
        return 0
    refreshed = market_data.best_pairs(market_data.tokens(list(pairs), opener=fetch))
    pairs.update({m: p for m, p in refreshed.items() if m in pairs})
    records: list[dict] = [market_data.market_record(pair, as_of) for pair in pairs.values()]

    for mint in pairs:
        if rpc_url and mint not in known_launch:
            try:  # authorities are best-effort: a public-RPC hiccup must not kill the run
                facts = market_data.mint_facts(rpc_url, mint, as_of, poster=poster)
            except (RuntimeError, OSError):
                continue
            if facts:
                records.append(facts)

    window_start = as_of - params.window_hours * 3600
    metrics = market_data.aggregate([*existing, *records], window_start, as_of, params)
    hubs = market_data.min_hubs() if holders else frozenset()
    for m in metrics:
        if not _passes_cheap_filters(m, params):
            continue
        if as_of - last_hourly.get(m.mint, 0) < hourly_due:
            continue
        launch = [r for r in records + existing if r["mint"] == m.mint and r["kind"] == "launch"]
        supply = int(launch[-1].get("supply") or 0) if launch else 0
        if holders and rpc_url and supply:
            try:
                top10 = market_data.top10_pct(rpc_url, m.mint, supply, hubs=hubs, poster=poster)
            except (RuntimeError, OSError):
                top10 = None
            if top10 is not None:
                records.append({"kind": "holders", "ts": as_of, "mint": m.mint, "top10_pct": top10})
        if helius_key:
            try:
                history = market_data.helius_history(
                    helius_key, m.mint, since_ts=window_start, until_ts=as_of, poster=poster
                )
                traders = market_data.unique_traders(history, since_ts=window_start, until_ts=as_of)
            except (RuntimeError, OSError):
                continue
            records.append({"kind": "flow", "ts": as_of, "mint": m.mint, "unique_traders": traders})
            creator = market_data.creator_from_history(history)
            if creator and rpc_url and supply:
                try:
                    dev = market_data.dev_pct(rpc_url, m.mint, creator, supply, poster=poster)
                except (RuntimeError, OSError):
                    dev = None
                if dev is not None:
                    records.append({"kind": "holders", "ts": as_of, "mint": m.mint, "dev_pct": dev})
    return market_data.append_samples(str(samples_path), records)


def run(
    *,
    as_of: str,
    out_dir: Path,
    samples_path: Path,
    params_path: Path = PARAMS,
    overrides_path: Path = OVERRIDES,
    offline: bool = False,
    skip_filters: tuple[str, ...] | None = None,
    rpc_url: str | None = None,
    helius_key: str | None = None,
    holders: bool = False,
    code_commit: str | None = None,
    collect_only: bool = False,
    official: bool = False,
) -> Path:
    ts = parse_iso(as_of)
    params = IndexParams.model_validate_json(params_path.read_text(encoding="utf-8"))
    if skip_filters is None:  # F4 has no source yet: dry-run default; official never skips
        skip_filters = () if official else ("F4",)
    if official:  # refuse before any network call or file write (issue #166)
        if skip_filters:
            raise OfficialRefusal(f"official run cannot skip filters: {', '.join(skip_filters)}")
        if params.self_mint is None:
            raise OfficialRefusal("official run needs params.self_mint (the index coin mint)")
    overrides = Overrides.model_validate_json(overrides_path.read_text(encoding="utf-8"))
    if skip_filters:
        params = params.model_copy(update={"dry_run": DryRun(skip_filters=skip_filters)})

    if not offline:
        collect(
            samples_path,
            ts,
            params,
            overrides,
            rpc_url=rpc_url,
            helius_key=helius_key,
            holders=holders,
        )
    if collect_only:
        print(f"sampled {as_of} -> {samples_path}")
        return samples_path

    window_start = ts - params.window_hours * 3600
    candidates = market_data.aggregate(
        market_data.read_samples(str(samples_path)), window_start, ts, params
    )
    if not candidates:
        raise ValueError(f"no samples for {as_of} in {samples_path}")

    as_of_iso = datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")
    date = as_of_iso[:10]
    dry_run = bool(params.dry_run.skip_filters)
    name = f"{date}.dryrun.json" if dry_run else f"{date}.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = run_index(
        candidates,
        previous_members(out_dir, name),
        params,
        overrides,
        as_of_iso,
        code_commit or _git_commit(),
    )
    if output["dry_run"] != dry_run:  # pragma: no cover - defensive
        raise RuntimeError("dry_run flag mismatch")
    if official:
        missing = sorted(e["mint"] for e in output["excluded"] if e["reason"] == MISSING)
        if missing:
            raise OfficialRefusal(
                f"official run has {len(missing)} candidate(s) with insufficient_data: "
                + ", ".join(missing[:5])
            )
    path = out_dir / name
    path.write_bytes(canonical_json(output) + b"\n")
    print(
        f"{date}: {len(candidates)} candidates, {len(output['members'])} members, "
        f"{len(output['excluded'])} excluded -> {path}"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute one GTA 6 index rebalance.")
    parser.add_argument("--as-of", required=True, help="rebalance time, ISO-8601 (default 18:00Z)")
    parser.add_argument("--out", default=str(ROOT / "index" / "out"), help="output directory")
    parser.add_argument(
        "--samples", default=None, help="JSONL sample path (default data/index/...)"
    )
    parser.add_argument("--params", default=str(PARAMS))
    parser.add_argument("--overrides", default=str(OVERRIDES))
    parser.add_argument("--offline", action="store_true", help="aggregate existing samples only")
    parser.add_argument(
        "--skip-filters",
        nargs="*",
        default=None,
        help="filters to skip, marking the output dry_run (default: F4 until its source is wired)",
    )
    parser.add_argument("--rpc-url", default=os.environ.get("SOLANA_RPC_URL") or None)
    parser.add_argument("--holders", action="store_true", help="also collect F3 hourly samples")
    parser.add_argument(
        "--collect-only", action="store_true", help="append a sample, do not compute the index"
    )
    parser.add_argument("--code-commit", default=None)
    parser.add_argument(
        "--official",
        action="store_true",
        help="official run: no skipped filters, self_mint set, no insufficient_data; else exit 3",
    )
    args = parser.parse_args(argv)

    samples = Path(args.samples) if args.samples else SAMPLES / f"{args.as_of[:10]}.jsonl"
    default_skip = () if args.official else ("F4",)
    skip = default_skip if args.skip_filters is None else tuple(args.skip_filters)
    try:
        run(
            as_of=args.as_of,
            out_dir=Path(args.out),
            samples_path=samples,
            params_path=Path(args.params),
            overrides_path=Path(args.overrides),
            offline=args.offline,
            skip_filters=skip,
            rpc_url=args.rpc_url,
            helius_key=os.environ.get("HELIUS_API_KEY") or None,
            holders=args.holders,
            code_commit=args.code_commit,
            collect_only=args.collect_only,
            official=args.official,
        )
    except OfficialRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
