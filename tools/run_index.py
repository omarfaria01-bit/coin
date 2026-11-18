#!/usr/bin/env python3
"""Read-only GTASP10 index run. No signing, no sends.

    HELIUS_API_KEY=... uv run python tools/run_index.py \\
        --as-of 2026-11-18T19:00:00+00:00 --out index/out --mode rebalance

The window is the trailing `window_hours` ending at `--as-of` (any hour, not a
calendar day). Samples in `--samples` count when their timestamp is inside that
window, including the previous UTC date. A token younger than the window is
scored on its own life. A member whose new hour is missing keeps its last
passing metrics. DexScreener is used only for liquidity and, when Helius has
no price, for price and market cap. The key is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import base58  # noqa: E402

from adapters.helius_client import HeliusClient  # noqa: E402
from adapters.hubs import load_hubs  # noqa: E402
from adapters.index_collect import discover_mints, measure_mints  # noqa: E402
from adapters.market_data import Sample  # noqa: E402
from index.filters import (  # noqa: E402
    Metrics,
    candidate_status,
    first_failed_filter,
    keyword_hit,
)
from index.params import IndexParams, Overrides, frac  # noqa: E402
from index.select import canonical_json, run_index  # noqa: E402


class OfficialRefusal(Exception):
    """An official run was refused; nothing is written and the previous file stays (issue #166)."""


def main(
    argv: list[str] | None = None,
    *,
    client: HeliusClient | None = None,
    measure: Callable | None = None,
    discover: Callable | None = None,
) -> int:
    args = _parser().parse_args(argv)
    params = IndexParams.model_validate(json.loads(Path(args.params).read_text()))
    overrides = Overrides.model_validate(json.loads(Path(args.overrides).read_text()))
    as_of = _unix(args.as_of)
    if client is None:
        key = os.environ.get("HELIUS_API_KEY", "").strip()
        if not key:
            print("HELIUS_API_KEY is not set", file=sys.stderr)
            return 2
        client = HeliusClient(key, max_history_pages=args.max_history_pages)
    try:
        found = discover or discover_mints
        if args.mode == "sample":
            from tools.index_watch import run_sample

            run_sample(args, client, params, overrides, as_of, found)
        elif args.mode == "emergency":
            from tools.index_watch import run_emergency

            run_emergency(args, client, params, as_of)
        else:
            _rebalance(
                args,
                client,
                params,
                overrides,
                as_of,
                measure or measure_mints,
                found,
            )
    except OfficialRefusal as exc:
        print(f"official run refused: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # leave any previous output file in place
        print(f"index run failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    counts = client.requests
    known = 10 * (counts["das"] + counts["parsed"])
    print(
        f"helius_requests rpc={counts['rpc']} das={counts['das']} "
        f"parsed={counts['parsed']} dex={counts['dex']} credits_known={known}"
    )
    return 0


def _rebalance(args, client, params, overrides, as_of, measure, discover) -> None:
    if args.official and not params.self_mint:  # refuse before any network call or write
        raise OfficialRefusal("official run needs params.self_mint (the index coin mint)")
    mints = _mints(args, client, params, overrides, discover)
    window = as_of - params.window_hours * 3600
    if not mints and _latest(Path(args.out)) is not None:
        raise RuntimeError("no mints")
    rows = measure(
        client,
        mints,
        as_of=as_of,
        window_start=window,
        hubs=load_hubs(),
        treasury=None,
        samples=[row for row in _load_samples(Path(args.samples)) if window <= row.t < as_of],
        fetched_at=_iso(as_of),
        sample_seconds=params.sample_minutes * 60,
        holder_seconds=params.holder_sample_minutes * 60,
        prescreen_liquidity_usd=float(
            frac(params.filters.min_liquidity_usd)
            * frac(params.discovery.prescreen_liquidity_share)
        ),
        dex_fee_rate=float(frac(params.filters.dex_fee_rate)),
    )
    if not rows and _latest(Path(args.out)) is not None:
        raise RuntimeError("no measurements")
    previous = _latest_payload(Path(args.out))
    rows, held = _hold_missing(rows, previous, params, overrides)
    if args.official:
        missing = [
            row.mint
            for row in rows
            if (candidate_status(row, params, overrides) or first_failed_filter(row, params))
            == "insufficient_data"
        ]
        if missing:
            raise OfficialRefusal(f"{len(missing)} candidate(s) with insufficient_data")
    prev = [row["mint"] for row in (previous or {}).get("members") or []]
    payload = run_index(rows, prev, params, overrides, _iso(as_of), _commit(), ())
    if params.rebalance_hours == 1:
        from tools.index_watch import defer_exit

        payload = defer_exit(payload, previous, params)
    if held:
        payload["data_hold"] = held
    _atomic(Path(args.out) / _out_name(as_of, params, bool(payload["dry_run"])), payload)


def _mints(args, client, params, overrides, discover) -> list[str]:
    # D37: top-down DexScreener search; --discover-pages 0 turns discovery off (seed file only).
    found = discover(client, params) if args.mode != "emergency" and args.discover_pages else []
    extra = list(_prev_members(Path(args.out)))
    if args.mints_file:
        for line in Path(args.mints_file).read_text().splitlines():
            text = line.split("#", 1)[0].strip()
            if text:
                extra.append(text)
    return _choose(params, overrides, found, extra)


def _choose(
    params: IndexParams, overrides: Overrides, found: list[dict], extra: list[str]
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in found:
        mint = row.get("mint")
        if not isinstance(mint, str) or mint in seen or not _valid(mint):
            continue
        name, symbol = str(row.get("name") or ""), str(row.get("symbol") or "")
        status = candidate_status(Metrics(mint=mint, ticker=symbol, name=name), params, overrides)
        text = f"{name} {symbol}"
        maybe = any(keyword_hit(text, k) for k in params.keywords.needs_context)
        if status == "self" or (status == "no_keyword" and not maybe):
            continue
        seen.add(mint)
        out.append(mint)
    for mint in extra:
        if _valid(mint) and mint not in seen and mint != params.self_mint:
            seen.add(mint)
            out.append(mint)
    return out


def _hold_missing(rows, previous, params, overrides) -> tuple[list[Metrics], list[str]]:
    """Keep a member whose new hour is missing, using its last passing metrics."""
    if not previous:
        return list(rows), []
    out = list(rows)
    index = {row.mint: i for i, row in enumerate(out)}
    held: list[str] = []
    for member in previous.get("members") or []:
        slot = index.get(member["mint"])
        if slot is None:
            continue
        reason = candidate_status(out[slot], params, overrides) or first_failed_filter(
            out[slot], params
        )
        if reason != "insufficient_data":
            continue
        raw = dict(member["metrics"])
        raw["sources"] = dict(raw.get("sources") or {})
        restored = Metrics(**raw)
        if candidate_status(restored, params, overrides) or first_failed_filter(restored, params):
            continue
        out[slot] = restored
        held.append(member["mint"])
    return out, held


def _out_name(as_of: int, params: IndexParams, dry: bool) -> str:
    stamp = _iso(as_of)
    stem = stamp[:13] if params.rebalance_hours == 1 else stamp[:10]
    return stem + (".dryrun.json" if dry else ".json")


def _latest_payload(out: Path) -> dict | None:
    path = _latest(out)
    if path is None:
        return None
    return json.loads(path.read_text())


def _load_samples(directory: Path) -> list[Sample]:
    rows: list[Sample] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn last line while a 5-minute sample is appending (D35)
            rows.append(
                Sample(
                    item["mint"],
                    int(item["t"]),
                    mc_usd=item.get("mc_usd"),
                    liquidity_usd=item.get("liquidity_usd"),
                    volume_usd=item.get("volume_usd"),
                    top10_pct=item.get("top10_pct"),
                )
            )
    return rows


def _prev_members(out: Path) -> list[str]:
    path = _latest(out)
    if path is None:
        return []
    payload = json.loads(path.read_text())
    return [row["mint"] for row in payload.get("members") or []]


def _latest(out: Path) -> Path | None:
    if not out.is_dir():
        return None
    files = [p for p in out.glob("*.json") if p.name != "emergency.json"]
    return max(files, default=None)


def _atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(canonical_json(payload))
    tmp.replace(path)


def _valid(mint: str) -> bool:
    try:
        return len(base58.b58decode(mint)) == 32
    except ValueError:
        return False


def _unix(text: str) -> int:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("as-of needs a timezone")
    return int(dt.timestamp())


def _iso(unix: int) -> str:
    return datetime.fromtimestamp(unix, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only GTASP10 index")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out", default="index/out")
    parser.add_argument("--params", default="index/params.json")
    parser.add_argument("--overrides", default="index/overrides.json")
    parser.add_argument("--samples", default="data/index/samples")
    parser.add_argument("--mints-file")
    parser.add_argument("--discover-pages", type=int, default=25)
    parser.add_argument("--max-history-pages", type=int, default=30)
    parser.add_argument(
        "--official",
        action="store_true",
        help="official run: self_mint set and no insufficient_data candidate; else exit 3",
    )
    parser.add_argument("--mode", choices=("rebalance", "sample", "emergency"), default="rebalance")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
