"""D37 (kiwi 18 Nov): GTA vocabulary with context words, top-down discovery, named gaps."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.index_collect import discover_mints
from index.filters import Metrics, candidate_status, gta_match, missing_metrics
from index.params import IndexParams, Overrides
from index.select import run_index

ROOT = Path(__file__).resolve().parent.parent
P = IndexParams.model_validate(json.loads((ROOT / "index/params.json").read_text()))
OV = Overrides()
GTA6 = "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"


def test_ambiguous_words_need_gta_context() -> None:
    assert gta_match("GTA VI", P)
    assert gta_match("AudaCity DacityCoin", P)
    assert not gta_match("Jason", P)  # Jason alone is any Jason
    assert not gta_match("Vice", P)
    assert gta_match("Jason Lucia", P)  # Lucia is a strong word
    assert gta_match("Jason and Vice", P)  # two different ambiguous words = GTA context
    assert gta_match("Jason the gangster of Vice City", P)
    m = Metrics(mint=GTA6, ticker="JASON", name="Jason", description="the GTA 6 hero")
    assert candidate_status(m, P, OV) is None


def test_missing_metric_is_named_not_silent() -> None:
    m = Metrics(
        mint=GTA6,
        ticker="GTA6",
        name="GTA VI",
        coverage=1.0,
        age_hours=500.0,
        liquidity_usd=200_000.0,
        mc_usd=13_000_000.0,
    )
    assert "top10_pct" in missing_metrics(m, P)
    out = run_index([m], [], P, OV, "2026-11-18T11:00:00Z", "abc")
    row = out["excluded"][0]
    assert row["reason"] == "insufficient_data"
    assert row["missing"][0] == "top10_pct" and row["mc_usd"] == 13_000_000.0


class _Search:
    requests = {"dex": 0}

    def search(self, term: str) -> list[dict]:
        def pair(mint: str, name: str, sym: str, mc: float, vol: float, chain: str = "solana"):
            return {
                "chainId": chain,
                "baseToken": {"address": mint, "name": name, "symbol": sym},
                "marketCap": mc,
                "liquidity": {"usd": mc / 20},
                "volume": {"h24": vol},
            }

        return [
            pair("A" * 32, "GTA VI", "GTA6", 13e6, 1e5),
            pair("B" * 32, "Vice City", "VICE", 2e6, 9e6),  # trending
            pair("C" * 32, "Random Dog", "DOG", 99e6, 9e7),  # not GTA
            pair("D" * 32, "GTA eth", "GTA", 50e6, 1e6, chain="ethereum"),
            pair("E" * 32, "Jason", "JASON", 1e6, 1.0),  # ambiguous: final check needs context
        ]


def test_discovery_is_top_down_trending_first_never_pump_history() -> None:
    rows = discover_mints(_Search(), P)  # type: ignore[arg-type]
    mints = [r["mint"] for r in rows]
    assert "C" * 32 not in mints and "D" * 32 not in mints
    assert mints[0] == "B" * 32  # highest h24 volume first (trending priority)
    assert mints.index("A" * 32) < mints.index("E" * 32)  # then by market cap


def test_d38_pool_totals_sum_real_pools_only() -> None:
    from adapters.index_collect import _pool_totals

    m = "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"
    pools = [
        {
            "pairAddress": "a",
            "baseToken": {"address": m},
            "liquidity": {"usd": 169_000},
            "volume": {"h24": 7_100_000},
        },
        {
            "pairAddress": "a",
            "baseToken": {"address": m},
            "liquidity": {"usd": 169_000},
            "volume": {"h24": 7_100_000},
        },
        {
            "pairAddress": "b",
            "baseToken": {"address": m},
            "liquidity": {"usd": 400_000},
            "volume": {"h24": 600_000},
        },
        {
            "pairAddress": "c",
            "baseToken": {"address": m},
            "liquidity": {"usd": 258},
            "volume": {"h24": 417_000},
        },
        {
            "pairAddress": "d",
            "baseToken": {"address": "other"},
            "liquidity": {"usd": 1e6},
            "volume": {"h24": 1e6},
        },
    ]
    assert _pool_totals(pools, m) == (569_000.0, 7_700_000.0)


def test_d38_scaled_never_shrinks() -> None:
    from adapters.index_observe import _scaled

    assert _scaled(100.0, 3.0) == 300.0
    assert _scaled(100.0, 0.5) == 100.0
    assert _scaled(100.0, None) == 100.0
    assert _scaled(None, 2.0) is None


def test_d38_no_candidate_is_silent() -> None:
    """Every candidate is a member or an excluded row with a reason (no_keyword, rank_n, ...)."""
    import json
    from pathlib import Path

    from index.filters import Metrics
    from index.params import IndexParams, Overrides
    from index.select import run_index

    params = IndexParams.model_validate(json.loads(Path("index/params.json").read_text()))
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

    def mint(i: int) -> str:
        return (alphabet[i % 58] + alphabet[(i // 58) % 58]) * 16 + "pump"

    good = dict(
        coverage=1.0,
        age_hours=100.0,
        liquidity_usd=200_000.0,
        top10_pct=20.0,
        total_fees_sol=50.0,
        trading_fees_24h_sol=50.0,
        window_fees_sol=5.0,
        bundle_pct=1.0,
        dev_pct=1.0,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=500,
        independent_traders=500,
        roundtrip_share=0.0,
        volume_wallets=300,
        median_trade_sol=0.1,
        volume_usd=500_000.0,
    )
    rows = [
        Metrics(mint=mint(i), ticker=f"GTA{i}", name="GTA 6", mc_usd=1e6 + i, **good)
        for i in range(14)
    ]
    rows.append(Metrics(mint=mint(20), ticker="DOG", name="dog coin", mc_usd=1e6, **good))
    rows.append(Metrics(mint=mint(21), ticker="", name="", mc_usd=None))
    out = run_index(rows, [], params, Overrides(), "2026-11-18T12:00:00Z", "abcdef0")
    listed = {m["mint"] for m in out["members"]} | {e["mint"] for e in out["excluded"]}
    assert listed == {r.mint for r in rows}
    reasons = {e["mint"]: e["reason"] for e in out["excluded"]}
    assert reasons[mint(20)] == "no_keyword" and reasons[mint(21)] == "no_keyword"
    assert sum(r.startswith("rank_") for r in reasons.values()) == 4


def test_d41_snapmatic_vocabulary() -> None:
    import json
    from pathlib import Path

    from index.filters import gta_match
    from index.params import IndexParams

    p = IndexParams.model_validate(json.loads(Path("index/params.json").read_text()))
    for text in (
        "Hugh Johnson HUGH",
        "hughjohnson",
        "Snapmatic",
        "Lifeinvader",
        "Bleeter",
        "Weazel News",
        "iFruit",
        "Eyefind",
        "in-game meme",
        "Hugh Johnson Core",
        "Johnson Vice",
    ):
        assert gta_match(text, p), text
    for text in ("Hugh Coin", "core meme", "johnson meme", "MEME", "Core", "Johnson & Johnson"):
        assert not gta_match(text, p), text
