"""Spot fold. No network (#161)."""

from __future__ import annotations

from adapters.index_observe import metrics_from, spot_quote

FACTS = {
    "symbol": "GTASP10",
    "name": "GTASP10",
    "description": "",
    "mc_usd": 2_000.0,
    "liquidity_usd": 60_000.0,
    "volume_usd": 1_000.0,
    "top10_pct": 20.0,
    "total_fees_sol": 0.003005,
    "window_fees_sol": 0.003005,
    "unique_traders": 1,
    "bundle_pct": 0.0,
    "dev_pct": 5.0,
    "creator_launches_7d": 1,
    "mint_authority_revoked": True,
    "freeze_authority_revoked": True,
    "age_hours": 1.0,
    "price_source": "helius-das",
    "program": "Tokenkeg",
}


def test_one_sample_cannot_cover_the_window() -> None:
    row = metrics_from(
        "mint",
        FACTS,
        [],
        as_of=900,
        window_start=0,
        sample_seconds=300,
        holder_seconds=3_600,
        fetched_at="t",
    )
    assert row.coverage == 1 / 3
    assert row.mc_usd == 2_000.0 and row.liquidity_usd == 60_000.0
    assert row.ticker == "GTASP10"
    assert row.sources["mc_usd"] == "helius-das@t"
    assert row.sources["liquidity_usd"] == "dexscreener@t"
    assert row.total_fees_sol == 0.003005


def test_helius_price_beats_dex_market_cap() -> None:
    pair = {"liquidity": {"usd": 10}, "volume": {"h24": 4}, "marketCap": 9_999}
    got = spot_quote(pair, {"price": 2.0}, supply=1_000, decimals=0)
    assert got["mc_usd"] == 2_000.0 and got["price_source"] == "helius-das"
    assert got["liquidity_usd"] == 10 and got["volume_usd"] == 4
    missing = spot_quote(pair, {}, supply=1_000, decimals=0)
    assert missing["mc_usd"] == 9_999 and missing["price_source"] == "dexscreener"
