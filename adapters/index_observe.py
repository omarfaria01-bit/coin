"""Fold a spot reading and stored samples into index Metrics. No I/O.

Helius price wins. DexScreener supplies liquidity and h24 volume, and price
or market cap only when DAS has none. One sample cannot pretend to cover the window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from adapters.market_data import Sample, aggregate_samples, market_cap_usd
from index.filters import Metrics


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def spot_quote(
    pair: Mapping[str, object] | None,
    asset: Mapping[str, object],
    supply: int | None,
    decimals: int | None,
) -> dict[str, object]:
    """Helius price wins. Dex fills liquidity, volume, and price only if DAS has none."""
    price = asset.get("price") if isinstance(asset.get("price"), (int, float)) else None
    mc = market_cap_usd(price if isinstance(price, (int, float)) else None, supply, decimals)
    liq = vol = None
    source = "helius-das" if mc is not None else None
    if pair is not None:
        block = pair.get("liquidity")
        liq = _num(block.get("usd")) if isinstance(block, Mapping) else None
        block = pair.get("volume")
        vol = _num(block.get("h24")) if isinstance(block, Mapping) else None
        if mc is None:
            mc = _num(pair.get("marketCap"))
            source = "dexscreener" if mc is not None else None
    return {"mc_usd": mc, "liquidity_usd": liq, "volume_usd": vol, "price_source": source}


def metrics_from(
    mint: str,
    facts: Mapping[str, object],
    samples: Sequence[Sample],
    *,
    as_of: int,
    window_start: int,
    sample_seconds: int,
    holder_seconds: int,
    fetched_at: str,
) -> Metrics:
    """Fold spot facts and stored samples into one Metrics. One sample cannot fake coverage."""
    spot = Sample(
        mint,
        as_of - 1,
        mc_usd=_opt(facts.get("mc_usd")),
        liquidity_usd=_opt(facts.get("liquidity_usd")),
        volume_usd=_opt(facts.get("volume_usd")),
        top10_pct=_opt(facts.get("top10_pct")),
    )
    own = [s for s in samples if s.mint == mint and window_start <= s.t < as_of]
    rows = own or [spot]
    stats = aggregate_samples(rows, window_start, as_of, sample_seconds, holder_seconds)
    src = str(facts.get("price_source") or "missing")
    tag = {
        "helius-das": f"helius-das@{fetched_at}",
        "dexscreener": f"dexscreener@{fetched_at}",
    }.get(src, f"missing@{fetched_at}")
    chain = f"helius-parsed-events@{fetched_at}"
    rpc = f"helius-rpc@{fetched_at}"
    return Metrics(
        mint=mint,
        ticker=str(facts.get("symbol") or ""),
        name=str(facts.get("name") or ""),
        description=str(facts.get("description") or ""),
        coverage=stats.coverage,
        age_hours=_opt(facts.get("age_hours")),
        liquidity_usd=stats.liquidity_usd,
        mc_usd=stats.mc_usd,
        top10_pct=stats.top10_pct,
        total_fees_sol=_opt(facts.get("total_fees_sol")),
        window_fees_sol=_opt(facts.get("window_fees_sol")),
        bundle_pct=_opt(facts.get("bundle_pct")),
        dev_pct=_opt(facts.get("dev_pct")),
        creator_launches_7d=_int_opt(facts.get("creator_launches_7d")),
        mint_authority_revoked=_bool_opt(facts.get("mint_authority_revoked")),
        freeze_authority_revoked=_bool_opt(facts.get("freeze_authority_revoked")),
        token_program=facts["program"] if isinstance(facts.get("program"), str) else None,
        extensions=_ext_opt(facts.get("mint_extensions")),
        unique_traders=_int_opt(facts.get("unique_traders")),
        volume_usd=stats.volume_usd,
        independent_traders=_int_opt(facts.get("independent_traders")),
        roundtrip_share=_opt(facts.get("roundtrip_share")),
        volume_wallets=_int_opt(facts.get("volume_wallets")),
        median_trade_sol=_opt(facts.get("median_trade_sol")),
        sources={
            "mc_usd": tag,
            "liquidity_usd": f"dexscreener@{fetched_at}",
            "volume_usd": f"dexscreener@{fetched_at}",
            "top10_pct": rpc,
            "total_fees_sol": chain,
            "window_fees_sol": chain,
            "unique_traders": chain,
            "independent_traders": chain,
            "roundtrip_share": chain,
            "volume_wallets": chain,
            "median_trade_sol": chain,
            "bundle_pct": chain,
            "dev_pct": rpc,
            "creator_launches_7d": chain,
            "age_hours": chain,
            "mint_authority_revoked": rpc,
            "freeze_authority_revoked": rpc,
            "mint_program": f"{facts.get('program')}@{fetched_at}",
        },
    )


def _ext_opt(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        return None
    return tuple(value)


def _opt(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int_opt(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bool_opt(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
