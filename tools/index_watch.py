"""Sample quotes and the hourly emergency check for the GTASP10 index. Read-only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from adapters.helius_client import HeliusClient
from adapters.helius_parse import (
    excluded_owners,
    parse_asset,
    parse_largest,
    parse_mint_account,
)
from adapters.hubs import load_hubs
from adapters.index_observe import spot_quote
from adapters.market_data import Sample, authorities_revoked, pick_pair, top10_pct
from index.emergency import apply_emergency
from index.params import IndexParams
from index.select import emergency_reason, mc_volume_of, weights_bps
from tools.run_index import (
    _atomic,
    _iso,
    _latest,
    _load_samples,
    _mints,
)


def run_sample(args, client, params, overrides, as_of: int, discover) -> None:
    mints = _mints(args, client, params, overrides, discover)
    pairs = client.pairs(mints) if mints else []
    holders = datetime.fromtimestamp(as_of, UTC).minute < params.sample_minutes
    path = Path(args.samples) / f"{_iso(as_of)[:10]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for mint in mints:
            row = _quote(client, mint, pick_pair(pairs, mint), as_of, holders)
            fh.write(json.dumps(_sample_row(row), sort_keys=True) + "\n")


def run_emergency(args, client: HeliusClient, params: IndexParams, as_of: int) -> None:
    path = _latest(Path(args.out))
    if path is None:
        raise RuntimeError("no index output to check")
    output = json.loads(path.read_text())
    samples = _load_samples(Path(args.samples))
    for member in list(output.get("members") or []):
        mint = member["mint"]
        revoked = _revoked(client, mint)
        reason = emergency_reason(
            _liq_at(samples, mint, as_of, 0),
            _liq_at(samples, mint, as_of, 3600),
            revoked[0],
            revoked[1],
            False,
            params,
            (
                _liq_at(samples, mint, as_of, params.emergency.confirm_gap_s),
                _liq_at(samples, mint, as_of, params.emergency.confirm_gap_s + 3600),
            ),
        )
        if reason:
            output = apply_emergency(output, mint, reason, _iso(as_of), params)
    _atomic(path, output)
    _atomic(
        Path(args.out) / "emergency.json",
        {"at": _iso(as_of), "emergency": output.get("emergency", [])},
    )


def defer_exit(payload: dict, previous: dict | None, params: IndexParams) -> dict:
    """A rank exit waits one hour. A filter failure still leaves immediately."""
    notice = set((previous or {}).get("exit_notice") or [])
    stay = [
        item["mint"]
        for item in payload["changes"]["exited"]
        if str(item["reason"]).startswith("rank_") and item["mint"] not in notice
    ]
    payload["exit_notice"] = stay
    if not stay:
        return payload
    kept = {item["mint"]: item for item in (previous or {}).get("members") or []}
    payload["members"].extend(kept[mint] for mint in stay if mint in kept)
    payload["members"].sort(key=lambda item: (-item["log_s"], item["mint"]))
    for rank, item in enumerate(payload["members"], start=1):
        item["rank"] = rank
    order = [item["mint"] for item in payload["members"]]
    scores = {item["mint"]: item["log_s"] for item in payload["members"]}
    bps = weights_bps(order, scores, params, mc_volume_of(payload["members"]))
    for item in payload["members"]:
        item["weight_bps"] = bps[item["mint"]]
    gone = set(stay)
    payload["changes"]["exited"] = [
        item for item in payload["changes"]["exited"] if item["mint"] not in gone
    ]
    return payload


def _quote(client, mint: str, pair: object, as_of: int, holders: bool) -> Sample:
    raw = client.rpc("getAsset", {"id": mint, "options": {"showFungible": True}})
    asset = parse_asset(raw if isinstance(raw, dict) else {})
    info = client.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    value = info.get("value") if isinstance(info, dict) else None
    mint_acc = parse_mint_account(value if isinstance(value, dict) else None)
    supply = mint_acc["supply"] if mint_acc and isinstance(mint_acc["supply"], int) else None
    decimals = mint_acc["decimals"] if mint_acc and isinstance(mint_acc["decimals"], int) else None
    quote = spot_quote(pair if isinstance(pair, dict) else None, asset, supply, decimals)
    top = _top10(client, mint, supply) if holders else None
    return Sample(
        mint,
        as_of,
        mc_usd=quote["mc_usd"] if isinstance(quote["mc_usd"], float) else None,
        liquidity_usd=quote["liquidity_usd"] if isinstance(quote["liquidity_usd"], float) else None,
        volume_usd=quote["volume_usd"] if isinstance(quote["volume_usd"], float) else None,
        top10_pct=top,
    )


def _top10(client, mint: str, supply: int | None) -> float | None:
    largest = client.rpc("getTokenLargestAccounts", [mint])
    rows = largest.get("value") if isinstance(largest, dict) else None
    if not isinstance(rows, list):
        return None
    parsed = [row for row in rows if isinstance(row, dict)]
    addrs = [row["address"] for row in parsed if isinstance(row.get("address"), str)]
    accounts = client.rpc("getMultipleAccounts", [addrs, {"encoding": "jsonParsed"}])
    values = accounts.get("value") if isinstance(accounts, dict) else None
    holders = parse_largest(parsed, values if isinstance(values, list) else [])
    if holders is None:
        return None
    owners = [owner for owner, _ in holders if owner]
    infos = (
        client.rpc("getMultipleAccounts", [owners, {"encoding": "jsonParsed"}])
        if owners
        else {"value": []}
    )
    programs: dict[str, str | None] = {}
    info_rows = infos.get("value") if isinstance(infos, dict) else []
    for owner, info in zip(owners, info_rows or [], strict=False):
        programs[owner] = info.get("owner") if isinstance(info, dict) else None
    if any(owner and programs.get(owner) is None for owner, _ in holders):
        return None
    skip = excluded_owners(hubs=load_hubs(), curves=[], owner_programs=programs, treasury=None)
    return top10_pct(holders, supply, skip)


def _revoked(client, mint: str) -> tuple[bool | None, bool | None]:
    info = client.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    value = info.get("value") if isinstance(info, dict) else None
    parsed = parse_mint_account(value if isinstance(value, dict) else None)
    raw = parsed.get("info") if parsed else None
    return authorities_revoked(raw if isinstance(raw, dict) else None)


def _liq_at(samples: list[Sample], mint: str, as_of: int, ago: int) -> float | None:
    target = as_of - ago
    best: Sample | None = None
    for row in samples:
        if row.mint != mint or row.liquidity_usd is None or row.t > as_of:
            continue
        if ago and abs(row.t - target) > 900:
            continue
        if best is None or abs(row.t - target) < abs(best.t - target):
            best = row
    return None if best is None else best.liquidity_usd


def _sample_row(row: Sample) -> dict:
    return {
        "mint": row.mint,
        "t": row.t,
        "mc_usd": row.mc_usd,
        "liquidity_usd": row.liquidity_usd,
        "volume_usd": row.volume_usd,
        "top10_pct": row.top10_pct,
    }
