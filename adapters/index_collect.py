"""Read one mint from Helius and fold it into Metrics. No signing.

Discovery is parsed history of the pump.fun program, because DAS searchAssets
has no name query. DexScreener is only the batched token endpoint.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from adapters.helius_client import HeliusClient
from adapters.helius_parse import (
    PUMP_PROGRAM,
    excluded_owners,
    normalize_transaction,
    parse_asset,
    parse_largest,
    parse_mint_account,
)
from adapters.index_observe import metrics_from, spot_quote
from adapters.market_data import (
    Sample,
    authorities_revoked,
    bundle_pct,
    creator_launches,
    fee_totals,
    pick_pair,
    top10_pct,
)
from index.filters import Metrics


def _txs(raw: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    out = []
    for item in raw:
        tx = normalize_transaction(item)
        if tx is not None:
            out.append(tx)
    return out


def _owner_balance(result: object) -> int | None:
    if not isinstance(result, dict) or not isinstance(result.get("value"), list):
        return None
    total = 0
    for row in result["value"]:
        try:
            amount = int(row["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        if amount < 0:
            return None
        total += amount
    return total


def chain_facts(
    client: HeliusClient,
    mint: str,
    *,
    as_of: int,
    window_start: int,
    hubs: Iterable[str],
    treasury: str | None,
    pair: Mapping[str, object] | None,
) -> dict[str, object]:
    """On-chain facts for one mint. Raises if Helius fails; missing fields stay None."""
    raw_asset = client.rpc("getAsset", {"id": mint, "options": {"showFungible": True}})
    asset = parse_asset(raw_asset if isinstance(raw_asset, Mapping) else {})
    info_value = client.rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    # getAccountInfo's result is the whole result object; value is inside.
    value = info_value.get("value") if isinstance(info_value, dict) else None
    mint_acc = parse_mint_account(value if isinstance(value, dict) else None)
    supply = mint_acc["supply"] if mint_acc else None
    decimals = mint_acc["decimals"] if mint_acc else None
    revoked = authorities_revoked(mint_acc["info"] if mint_acc else None)  # type: ignore[arg-type]
    largest = client.rpc("getTokenLargestAccounts", [mint])
    rows = largest.get("value") if isinstance(largest, dict) else None
    holders = None
    programs: dict[str, str | None] = {}
    if isinstance(rows, list):
        addrs = [row.get("address") for row in rows if isinstance(row, Mapping)]
        accounts = _multiple(client, [a for a in addrs if isinstance(a, str)])
        holders = parse_largest([r for r in rows if isinstance(r, Mapping)], accounts)
        owners = [owner for owner, _ in holders or [] if owner]
        infos = _multiple(client, owners)
        for owner, info in zip(owners, infos, strict=True):
            programs[owner] = info.get("owner") if isinstance(info, dict) else None
        unknown = [owner for owner, _ in (holders or []) if owner and programs.get(owner) is None]
        if holders is not None and unknown:
            holders = [(None, amount) for _, amount in holders]
    curves: list[str | None] = []
    raw, truncated = client.history(mint, end=as_of)
    txs = _txs(raw)
    for tx in txs:
        creates = tx.get("creates")
        if isinstance(creates, list):
            curves.extend(row.get("bonding_curve") for row in creates if isinstance(row, Mapping))
    first_raw, _ = client.history(mint, end=as_of, sort="asc", max_pages=1, limit=1)
    first = _txs(first_raw)
    first_time = first[0].get("block_time") if first else None
    if isinstance(first_time, int) and any(
        isinstance(tx.get("block_time"), int) and tx["block_time"] > first_time for tx in txs
    ):
        oldest = min(tx["block_time"] for tx in txs if isinstance(tx.get("block_time"), int))
        if oldest > first_time:
            truncated = True
    creator = asset.get("creator") if isinstance(asset.get("creator"), str) else None
    for tx in txs:
        for row in tx.get("creates") or []:  # type: ignore[union-attr]
            if not isinstance(row, Mapping) or row.get("mint") != mint:
                continue
            creator_name = row.get("creator")
            if isinstance(creator_name, str):
                creator = creator_name
    skip = excluded_owners(hubs=hubs, curves=curves, owner_programs=programs, treasury=treasury)
    fees = fee_totals(txs, mint, window_start=window_start, window_end=as_of, truncated=truncated)
    supply_i = supply if isinstance(supply, int) else None
    launches = None
    if isinstance(creator, str):
        craw, ctrunc = client.history(creator, start=as_of - 7 * 86_400, end=as_of)
        created = [row for tx in _txs(craw) for row in (tx.get("creates") or [])]  # type: ignore[union-attr]
        launches = creator_launches(created, creator, as_of - 7 * 86_400, as_of, truncated=ctrunc)
    balance = None
    if isinstance(creator, str):
        owned = client.rpc(
            "getTokenAccountsByOwner",
            [creator, {"mint": mint}, {"encoding": "jsonParsed"}],
        )
        balance = _owner_balance(owned)
    dev = 100 * balance / supply_i if balance is not None and supply_i else None
    quote = spot_quote(pair, asset, supply_i, decimals if isinstance(decimals, int) else None)
    age = (as_of - first_time) / 3600 if isinstance(first_time, int) else None
    top10 = top10_pct(holders, supply_i, skip) if holders is not None else None
    return {
        "name": asset.get("name") or "",
        "symbol": asset.get("symbol") or "",
        "description": asset.get("description") or "",
        "program": mint_acc["program"] if mint_acc else None,
        "age_hours": age,
        "top10_pct": top10,
        "bundle_pct": bundle_pct(txs, mint, supply_i, skip),
        "dev_pct": dev,
        "creator_launches_7d": launches,
        "mint_authority_revoked": revoked[0],
        "freeze_authority_revoked": revoked[1],
        "total_fees_sol": fees.total_fees_sol,
        "window_fees_sol": fees.window_fees_sol,
        "unique_traders": None if fees.traders is None else len(fees.traders),
        **quote,
    }


def _multiple(client: HeliusClient, addrs: Sequence[str]) -> list[object]:
    if not addrs:
        return []
    result = client.rpc("getMultipleAccounts", [list(addrs), {"encoding": "jsonParsed"}])
    value = result.get("value") if isinstance(result, dict) else None
    if not isinstance(value, list) or len(value) != len(addrs):
        raise RuntimeError("helius getMultipleAccounts failed")
    return value


def discover_mints(client: HeliusClient, pages: int) -> list[dict[str, object]]:
    """Recent pump.fun creates from parsed history. DAS has no name search."""
    if pages <= 0:
        return []
    raw, _ = client.history(PUMP_PROGRAM, max_pages=pages)
    found: list[dict[str, object]] = []
    for tx in _txs(raw):
        creates = tx.get("creates")
        if isinstance(creates, list):
            found.extend(row for row in creates if isinstance(row, Mapping))
    return found


def measure_mints(
    client: HeliusClient,
    mints: Sequence[str],
    *,
    as_of: int,
    window_start: int,
    hubs: Iterable[str],
    treasury: str | None,
    samples: Sequence[Sample],
    fetched_at: str,
    sample_seconds: int,
    holder_seconds: int,
) -> list[Metrics]:
    """One read-only pass. DexScreener is batched. A Helius error aborts the pass."""
    found = client.pairs(list(mints)) if mints else []
    out: list[Metrics] = []
    for mint in mints:
        facts = chain_facts(
            client,
            mint,
            as_of=as_of,
            window_start=window_start,
            hubs=hubs,
            treasury=treasury,
            pair=pick_pair(found, mint),
        )
        start = window_start
        age = facts.get("age_hours")
        if isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0:
            start = max(window_start, as_of - int(age * 3600))
        out.append(
            metrics_from(
                mint,
                facts,
                samples,
                as_of=as_of,
                window_start=start,
                sample_seconds=sample_seconds,
                holder_seconds=holder_seconds,
                fetched_at=fetched_at,
            )
        )
    return out
