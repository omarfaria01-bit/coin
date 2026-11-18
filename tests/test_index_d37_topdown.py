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
