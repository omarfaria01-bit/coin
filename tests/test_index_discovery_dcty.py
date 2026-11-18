"""D44: DacityCoin (DCTY, 9hjBLB...) was invisible to discovery.

DexScreener search returns at most 30 pairs. On 18 Nov "Dacity" returned 30 copycats and not
the real coin ($11.3M MC, $24.8M 24h volume); "DCTY" returns it. The fake client below mimics
that: without the DCTY term the coin is never a candidate, with it the coin leads by volume.
"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.index_collect import discover_mints
from index.params import IndexParams

ROOT = Path(__file__).resolve().parents[1]
REAL = "9hjBLBrc7WZW2H8UQvBAvG5WiTZotXUv2Bdcn4f4pump"


def _pair(mint: str, name: str, symbol: str, mc: float, vol: float) -> dict[str, object]:
    return {
        "chainId": "solana",
        "baseToken": {"address": mint, "name": name, "symbol": symbol},
        "marketCap": mc,
        "liquidity": {"usd": mc / 30},
        "volume": {"h24": vol},
    }


class _FakeDex:
    def search(self, query: str) -> list[dict[str, object]]:
        if query == "Dacity":  # the 30-pair cap is full of copycats
            return [
                _pair(f"Copy{i:040d}", "Dacity Coin", "DACITY", 1000.0 + i, 10.0) for i in range(30)
            ]
        if query == "DCTY":
            return [_pair(REAL, "DacityCoin", "DCTY", 11_329_226.0, 24_788_375.5)]
        return []


def _params(with_dcty: bool) -> IndexParams:
    raw = json.loads((ROOT / "index/params.json").read_text())
    terms = raw["discovery"]["search_terms"]
    raw["discovery"]["search_terms"] = [t for t in terms if with_dcty or t != "DCTY"]
    return IndexParams.model_validate(raw)


def test_dcty_is_a_search_term() -> None:
    assert "DCTY" in _params(True).discovery.search_terms


def test_real_dacitycoin_found_only_with_ticker_search() -> None:
    without = [r["mint"] for r in discover_mints(_FakeDex(), _params(False))]
    found = [r["mint"] for r in discover_mints(_FakeDex(), _params(True))]
    assert REAL not in without
    assert found[0] == REAL  # highest 24h volume: collected first


def test_real_dacitycoin_is_seeded() -> None:
    seeds = (ROOT / "index/seed_mints.txt").read_text()
    assert any(line.split()[0] == REAL for line in seeds.splitlines() if line and line[0] != "#")
