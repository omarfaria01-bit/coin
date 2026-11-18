"""D42 (#300): buckme / $B / GTA 6 bank app is discovery vocabulary only.

Reference coin CA Cr8kuNqKwiVVuzqLYKcJhmpSHy767837BwLFr9GDYXUf (X @buckme_sol,
name ``buckme``, symbol ``b``). The mint is not seeded or allowlisted. It is a
candidate only because the name matches, and it still has to pass F1–F11.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from index.filters import Metrics, candidate_status, first_failed_filter, gta_match
from index.params import IndexParams, Overrides

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "Cr8kuNqKwiVVuzqLYKcJhmpSHy767837BwLFr9GDYXUf"
WORDS = ("buckme", "$B", "GTA 6 bank app", "gta6 bank", "bank app")


def _params() -> IndexParams:
    return IndexParams.model_validate(json.loads((ROOT / "index/params.json").read_text()))


def test_buckme_words_are_strong_and_searched() -> None:
    p = _params()
    for word in WORDS:
        assert word in p.keywords.strong
        assert word in p.discovery.search_terms
    for text in ("buckme", "$B", "GTA 6 bank app", "gta6 bank", "the bank app", "buckme.dev"):
        assert gta_match(text, p), text
    # Bare "b" is the live symbol and is not a keyword. "$BONK" / "bank" are not the phrase.
    for text in ("b", "B", "$BONK", "bank", "solana dog"):
        assert not gta_match(text, p), text


def test_example_name_matches_and_mint_is_not_included() -> None:
    p = _params()
    assert gta_match("buckme b", p)  # published name + symbol
    assert gta_match("buckme $B", p)
    seed = (ROOT / "index/seed_mints.txt").read_text()
    deny = json.loads((ROOT / "index/overrides.json").read_text())
    assert EXAMPLE not in seed
    assert EXAMPLE not in json.dumps(deny)
    assert p.self_mint != EXAMPLE


def _row(**kw: object) -> Metrics:
    base = Metrics(
        mint=EXAMPLE,
        ticker="b",
        name="buckme",
        description="GTA 6 bank app",
        coverage=1.0,
        age_hours=30.0,
        liquidity_usd=120_000.0,
        mc_usd=1_500_000.0,
        top10_pct=20.0,
        total_fees_sol=40.0,
        trading_fees_24h_sol=40.0,
        window_fees_sol=12.0,
        bundle_pct=3.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=900,
        independent_traders=900,
        roundtrip_share=0.0,
        volume_wallets=100,
        median_trade_sol=0.1,
        volume_usd=600_000.0,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_example_still_has_to_pass_the_filters() -> None:
    p = _params()
    ok = _row()
    assert candidate_status(ok, p, Overrides()) is None
    assert first_failed_filter(ok, p) is None
    thin = _row(liquidity_usd=1_000.0)
    assert candidate_status(thin, p, Overrides()) is None  # vocabulary only
    assert first_failed_filter(thin, p) == "F2"
