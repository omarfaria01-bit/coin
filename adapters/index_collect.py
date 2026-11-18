"""Read one mint from Helius and fold it into Metrics. No signing.

Discovery (D37) is top-down: DexScreener search for the GTA vocabulary, most established coins
first by market cap, plus the top h24-volume (trending) coins. It never walks new pump.fun
launches. Big coins have more history than the page cap: their window metrics are exact when the
fetched pages reach back past the window start, and F4/F9 accept a lower bound that already
passes the threshold. Anything still unknown is named in the output, never silent.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from adapters.helius_client import HeliusClient
from adapters.helius_parse import (
    excluded_owners,
    normalize_transaction,
    parse_asset,
    parse_largest,
    parse_mint_account,
)
from adapters.index_history_cache import fetch_mint_history_incremental
from adapters.index_observe import metrics_from, spot_quote
from adapters.market_data import (
    LAMPORTS_PER_SOL,
    Sample,
    authorities_revoked,
    bundle_pct,
    fee_totals,
    pick_pair,
    top10_pct,
    trade_quality,
)
from index.filters import Metrics, gta_match, keyword_hit
from index.params import Filters, IndexParams, frac


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
    try:  # D37: Helius refuses this for some mints; then top10 is named as missing, not fatal
        largest = client.rpc("getTokenLargestAccounts", [mint])
    except RuntimeError:
        largest = None
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
        # D37: an owner with no account on chain is a plain (empty) wallet, not a vault; it
        # counts as a holder (fail-safe: it can only raise top10), so top10 is never blank for it.
    curves: list[str | None] = []
    raw, truncated = fetch_mint_history_incremental(client, mint, as_of=as_of)
    txs = _txs(raw)
    for tx in txs:
        creates = tx.get("creates")
        if isinstance(creates, list):
            curves.extend(row.get("bonding_curve") for row in creates if isinstance(row, Mapping))
    first_raw, _ = client.history(mint, end=as_of, sort="asc", max_pages=1, limit=100)
    first = _txs(first_raw)
    first_time = first[0].get("block_time") if first else None
    if isinstance(first_time, int) and any(
        isinstance(tx.get("block_time"), int) and tx["block_time"] > first_time for tx in txs
    ):
        oldest = min(tx["block_time"] for tx in txs if isinstance(tx.get("block_time"), int))
        if oldest > first_time:
            truncated = True
    fetched = [tx["block_time"] for tx in txs if isinstance(tx.get("block_time"), int)]
    oldest_recent = min(fetched) if fetched else None
    if truncated:  # D37: the launch block comes from the oldest page (bundle, creator, curve)
        have = {tx.get("signature") for tx in txs}
        for tx in first:
            if tx.get("signature") not in have:
                txs.append(tx)
            for row in tx.get("creates") or []:  # type: ignore[union-attr]
                if isinstance(row, Mapping):
                    curves.append(row.get("bonding_curve"))
    creator = asset.get("creator") if isinstance(asset.get("creator"), str) else None
    for tx in txs:
        for row in tx.get("creates") or []:  # type: ignore[union-attr]
            if not isinstance(row, Mapping) or row.get("mint") != mint:
                continue
            creator_name = row.get("creator")
            if isinstance(creator_name, str):
                creator = creator_name
    skip = excluded_owners(hubs=hubs, curves=curves, owner_programs=programs, treasury=treasury)
    # D37: newest-first pages that reach back before the window start hold the whole window.
    window_whole = not truncated or (oldest_recent is not None and oldest_recent < window_start)
    fees = fee_totals(txs, mint, window_start=window_start, window_end=as_of, truncated=False)
    supply_i = supply if isinstance(supply, int) else None
    flt = Filters()  # D33: thresholds for the trade-quality facts are the published defaults
    quality = trade_quality(
        txs,
        mint,
        window_start=window_start,
        window_end=as_of,
        truncated=False,
        creator=creator,
        min_trader_lamports=math.ceil(frac(flt.min_trader_volume_sol) * LAMPORTS_PER_SOL),
        roundtrip_seconds=600,
        skip_unknown=True,  # D37: F9 is a minimum, so an uncounted odd swap only lowers the count
    )
    bounds: list[str] = []
    total_fees = fees.total_fees_sol
    if truncated:
        # Lifetime fees of the pages we have are a lower bound: enough when it already passes F4.
        if total_fees is not None and total_fees >= float(frac(flt.min_total_fees_sol)):
            bounds.append("total_fees_sol")
        else:
            total_fees = None
    independent = None if quality is None else quality.independent_traders
    if not window_whole:
        bounds.extend(["window_fees_sol", "unique_traders"])
        if independent is not None and independent >= flt.min_unique_traders:
            bounds.append("independent_traders")
        else:
            independent = None
    launches = None  # D38: F7 removed, the creator's 7-day history is no longer walked
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
        "mint_extensions": _extensions(mint_acc),
        "age_hours": age,
        "top10_pct": top10,
        "bundle_pct": bundle_pct(txs, mint, supply_i, skip, creator=creator),
        "dev_pct": dev,
        "creator_launches_7d": launches,
        "mint_authority_revoked": revoked[0],
        "freeze_authority_revoked": revoked[1],
        "total_fees_sol": total_fees,
        "window_fees_sol": fees.window_fees_sol,
        "unique_traders": None if fees.traders is None else len(fees.traders),
        "independent_traders": independent,
        "lower_bounds": bounds,
        "roundtrip_share": None if quality is None else quality.roundtrip_share,
        "volume_wallets": None if quality is None else quality.volume_wallets,
        "median_trade_sol": None if quality is None else quality.median_trade_sol,
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


def _f(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return float(value)


def discover_mints(client: HeliusClient, params: IndexParams) -> list[dict[str, object]]:
    """D37 top-down discovery. DexScreener search for each vocabulary term, Solana only.

    Returns rows ordered for collection priority: the `max_trending` coins with the highest
    h24 volume first, then the `max_by_mc` most established by market cap. A coin whose
    name/ticker has only ambiguous words is kept here; the final vocabulary check (with the
    on-chain description) happens in the run. New pump.fun launches are never walked.
    """
    if not isinstance(params, IndexParams):
        return []
    best: dict[str, dict[str, object]] = {}
    ctx = params.keywords.needs_context
    for term in params.discovery.search_terms:
        for pair in client.search(term):
            if pair.get("chainId") != "solana":
                continue
            base = pair.get("baseToken")
            if not isinstance(base, Mapping) or not isinstance(base.get("address"), str):
                continue
            name, symbol = str(base.get("name") or ""), str(base.get("symbol") or "")
            text = f"{name} {symbol}"
            if not gta_match(text, params) and not any(keyword_hit(text, k) for k in ctx):
                continue
            mint = str(base["address"])
            liq = pair.get("liquidity")
            vol = pair.get("volume")
            row = {
                "mint": mint,
                "name": name,
                "symbol": symbol,
                "mc_usd": _f(pair.get("marketCap") or pair.get("fdv")),
                "liquidity_usd": _f(liq.get("usd") if isinstance(liq, Mapping) else None),
                "volume_usd": _f(vol.get("h24") if isinstance(vol, Mapping) else None),
            }
            old = best.get(mint)
            if old is None:
                best[mint] = row
            else:  # one coin, many pools: keep the biggest market cap, add up the volume
                old["mc_usd"] = max(_f(old["mc_usd"]), _f(row["mc_usd"]))
                old["liquidity_usd"] = max(_f(old["liquidity_usd"]), _f(row["liquidity_usd"]))
                old["volume_usd"] = _f(old["volume_usd"]) + _f(row["volume_usd"])
    rows = list(best.values())
    by_mc = sorted(rows, key=lambda r: (-_f(r["mc_usd"]), str(r["mint"])))
    by_vol = sorted(rows, key=lambda r: (-_f(r["volume_usd"]), str(r["mint"])))
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in by_vol[: params.discovery.max_trending] + by_mc[: params.discovery.max_by_mc]:
        if row["mint"] not in seen:
            seen.add(str(row["mint"]))
            out.append(row)
    return out


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
    prescreen_liquidity_usd: float | None = None,
    dex_fee_rate: float = 0.0025,
) -> list[Metrics]:
    """One read-only pass. DexScreener is batched.

    D37: a Helius error on one mint no longer aborts the pass: that mint is published as
    insufficient_data with `helius_error` named. A mint whose best pool is below
    `prescreen_liquidity_usd` is not walked on chain (keeps the hourly run fast); it is
    scored from DexScreener alone and fails F2.
    """
    found = client.pairs(list(mints)) if mints else []
    sol_usd = _sol_usd(found)
    out: list[Metrics] = []
    for mint in mints:
        pair = pick_pair(found, mint)
        dex = _dex_facts(pair, as_of)
        liq = dex.get("liquidity_usd")
        if prescreen_liquidity_usd is not None and (
            pair is None or not isinstance(liq, float) or liq < prescreen_liquidity_usd
        ):
            facts = dict(dex, prescreen=True)
        else:
            facts = dict(dex, error="not_run")
            for _attempt in range(2):  # D38: one retry; a transient Helius error dropped GTA VI
                try:
                    facts = chain_facts(
                        client,
                        mint,
                        as_of=as_of,
                        window_start=window_start,
                        hubs=hubs,
                        treasury=treasury,
                        pair=pair,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - one mint's failure is published, not fatal
                    facts = dict(dex, error=type(exc).__name__)
        pools = _all_pools(client, mint) if not facts.get("prescreen") else None
        if pools:  # D38: liquidity, volume and fees summed over every real pool, not the top one
            liq_sum, vol_sum = _pool_totals(pools, mint)
            top_vol = dex.get("volume_usd")
            if liq_sum > 0 and isinstance(liq, float) and liq > 0:
                # The window median of 5-min samples is top-pool only; scale it by today's
                # all-pools / top-pool ratio (never below 1: the top pool always counts).
                facts = dict(facts, pool_liq_factor=max(1.0, liq_sum / liq))
                if isinstance(top_vol, float) and top_vol > 0:
                    facts["pool_vol_factor"] = max(1.0, vol_sum / top_vol)
            fees24 = vol_sum * dex_fee_rate / sol_usd if sol_usd and liq_sum > 0 else None
        else:
            fees24 = _trading_fees(found, mint, sol_usd, dex_fee_rate)
        facts = dict(facts, trading_fees_24h_sol=fees24)
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


WSOL = "So11111111111111111111111111111111111111112"
POOL_MIN_LIQUIDITY_USD = 10_000.0  # D38: a pool below this is ignored (dust / wash pools)


def _all_pools(client: HeliusClient, mint: str) -> list[Mapping[str, object]] | None:
    fetch = getattr(client, "token_pools", None)
    if fetch is None:
        return None
    try:
        return fetch(mint)
    except Exception:  # noqa: BLE001 - fall back to the top pool from the batch
        return None


def _pool_totals(pools: Sequence[Mapping[str, object]], mint: str) -> tuple[float, float]:
    """Sum (liquidity USD, h24 volume USD) over pools where `mint` is the base token and the
    pool holds at least POOL_MIN_LIQUIDITY_USD. Each pool address counts once."""
    liq_sum = vol_sum = 0.0
    seen: set[object] = set()
    for p in pools:
        base = p.get("baseToken")
        if not isinstance(base, Mapping) or base.get("address") != mint:
            continue
        addr = p.get("pairAddress")
        if addr in seen:
            continue
        seen.add(addr)
        liq = p.get("liquidity")
        usd = liq.get("usd") if isinstance(liq, Mapping) else None
        if isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd):
            continue
        if usd < POOL_MIN_LIQUIDITY_USD:
            continue
        vol = p.get("volume")
        h24 = vol.get("h24") if isinstance(vol, Mapping) else None
        liq_sum += float(usd)
        if isinstance(h24, (int, float)) and not isinstance(h24, bool) and math.isfinite(h24):
            vol_sum += max(float(h24), 0.0)
    return liq_sum, vol_sum


def _sol_usd(pairs: Sequence[Mapping[str, object]]) -> float | None:
    """SOL/USD from DexScreener pairs quoted in SOL (priceUsd / priceNative), median."""
    vals: list[float] = []
    for p in pairs:
        quote = p.get("quoteToken")
        if not isinstance(quote, Mapping) or quote.get("address") != WSOL:
            continue
        try:
            usd, native = float(p.get("priceUsd")), float(p.get("priceNative"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if native > 0 and usd > 0 and math.isfinite(usd / native):
            vals.append(usd / native)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def _trading_fees(
    pairs: Sequence[Mapping[str, object]], mint: str, sol_usd: float | None, rate: float
) -> float | None:
    """D38 F4: h24 volume of every pool of `mint` x fee rate, in SOL. None if unknown."""
    if not sol_usd:
        return None
    total = 0.0
    seen = False
    for p in pairs:
        base = p.get("baseToken")
        if not isinstance(base, Mapping) or base.get("address") != mint:
            continue
        vol = p.get("volume")
        h24 = vol.get("h24") if isinstance(vol, Mapping) else None
        if isinstance(h24, (int, float)) and not isinstance(h24, bool) and math.isfinite(h24):
            total += max(float(h24), 0.0)
            seen = True
    return total * rate / sol_usd if seen else None


def _dex_facts(pair: Mapping[str, object] | None, as_of: int) -> dict[str, object]:
    """What DexScreener alone says about a coin (prescreen / error rows)."""
    if pair is None:
        return {}
    base = pair.get("baseToken") if isinstance(pair.get("baseToken"), Mapping) else {}
    liq = pair.get("liquidity")
    vol = pair.get("volume")
    created = pair.get("pairCreatedAt")
    age = None
    if isinstance(created, (int, float)) and not isinstance(created, bool) and created > 0:
        age = max(0.0, (as_of - created / 1000) / 3600)
    mc = pair.get("marketCap") or pair.get("fdv")
    return {
        "name": str(base.get("name") or ""),  # type: ignore[union-attr]
        "symbol": str(base.get("symbol") or ""),  # type: ignore[union-attr]
        "mc_usd": float(mc) if isinstance(mc, (int, float)) and not isinstance(mc, bool) else None,
        "liquidity_usd": float(liq["usd"])
        if isinstance(liq, Mapping) and isinstance(liq.get("usd"), (int, float))
        else None,
        "volume_usd": float(vol["h24"])
        if isinstance(vol, Mapping) and isinstance(vol.get("h24"), (int, float))
        else None,
        "age_hours": age,
        "price_source": "dexscreener",
    }


def _extensions(mint_acc: Mapping[str, object] | None) -> list[str] | None:
    """Token-2022 extension names from the parsed mint (empty for legacy); None if unknown."""
    info = mint_acc.get("info") if mint_acc else None
    if not isinstance(info, Mapping):
        return None
    ext = info.get("extensions")
    if ext is None:
        return []
    if not isinstance(ext, list):
        return None
    names = [e.get("extension") for e in ext if isinstance(e, Mapping)]
    if len(names) != len(ext) or not all(isinstance(n, str) for n in names):
        return None  # unreadable entry: unknown, fail-safe
    return sorted(set(names))  # type: ignore[arg-type]
