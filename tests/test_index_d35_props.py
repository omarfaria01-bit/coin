"""Hypothesis property tests for D35 index rules (#239).

(1) Keywords matching rules (35 strong keywords, case-insensitive,
    word boundaries, bare VI/Jason missing).
(2) Coverage 0/None => insufficient_data, >0 not insufficient_data.
(3) Boundaries: age 4h, fees 8 SOL, bundle 30% pass; below/above fail F1/F4/F5.
(4) F10 fails only for volume <= 0.
(5) dev_pct never changes filter outcome.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import base58
from hypothesis import given, settings
from hypothesis import strategies as st

from index.filters import Metrics, candidate_status, first_failed_filter
from index.params import IndexParams, Overrides

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
NO = Overrides()


def mint(i: int) -> str:
    return base58.b58encode(bytes([i % 256]) * 32).decode()


def good(i: int = 1, **kw: object) -> Metrics:
    base = Metrics(
        mint=mint(i),
        ticker="GTA6",
        name="Vice City Dog",
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


@settings(max_examples=50)
@given(
    st.sampled_from(P.keywords.strong),
    st.sampled_from(["", " ", "$", "!", "-", "1", "9"]),
    st.sampled_from(["", " ", "$", "!", "-", "1", "9"]),
    st.booleans(),
    st.booleans(),
)
def test_d35_keyword_matching(
    kw: str, prefix: str, suffix: str, upper: bool, name_field: bool
) -> None:
    text = f"{prefix}{kw}{suffix}"
    text = text.upper() if upper else text.lower()
    name = text if name_field else "Coin"
    ticker = text if not name_field else "COIN"
    m = good(name=name, ticker=ticker, description="")
    touches_left = bool(prefix and prefix[-1].isalpha())
    touches_right = bool(suffix and suffix[0].isalpha())
    is_hit = not (touches_left or touches_right)
    expected = None if is_hit else "no_keyword"
    assert candidate_status(m, P, NO) == expected


@settings(max_examples=20)
@given(st.sampled_from(["VI", "Jason"]))
def test_bare_forbidden_keywords_never_match(forbidden: str) -> None:
    m = good(name=forbidden, ticker="COIN", description="")
    assert candidate_status(m, P, NO) == "no_keyword"


@settings(max_examples=20)
@given(st.sampled_from([0.0, None]))
def test_d35_coverage_zero_or_none_fails(cov: float | None) -> None:
    m = good(coverage=cov)
    assert first_failed_filter(m, P) == "insufficient_data"


@settings(max_examples=20)
@given(st.floats(min_value=1e-6, max_value=1.0))
def test_d35_coverage_positive_passes_filter(cov: float) -> None:
    m = good(coverage=cov)
    assert first_failed_filter(m, P) is None


@settings(max_examples=20)
@given(
    st.floats(min_value=0.0, max_value=3.9),
    st.floats(min_value=4.0, max_value=100.0),
    st.floats(min_value=0.0, max_value=7.99),
    st.floats(min_value=8.0, max_value=100.0),
    st.floats(min_value=30.01, max_value=100.0),
    st.floats(min_value=0.0, max_value=30.0),
)
def test_d35_boundaries_f1_f4_f5(
    age_bad: float,
    age_good: float,
    fees_bad: float,
    fees_good: float,
    bundle_bad: float,
    bundle_good: float,
) -> None:
    assert first_failed_filter(good(age_hours=age_bad), P) == "F1"
    assert first_failed_filter(good(age_hours=age_good), P) is None
    assert first_failed_filter(good(trading_fees_24h_sol=fees_bad), P) == "F4"  # D38 measure
    assert first_failed_filter(good(trading_fees_24h_sol=fees_good), P) is None
    assert first_failed_filter(good(bundle_pct=bundle_bad), P) == "F5"
    assert first_failed_filter(good(bundle_pct=bundle_good), P) is None


@settings(max_examples=20)
@given(st.floats(min_value=-100.0, max_value=0.0))
def test_f10_fails_on_non_positive_volume(vol: float) -> None:
    m = good(volume_usd=vol)
    assert first_failed_filter(m, P) == "F10"


@settings(max_examples=20)
@given(st.floats(min_value=0.0, max_value=100.0))
def test_dev_pct_never_changes_result(dev: float) -> None:
    base_res = first_failed_filter(good(), P)
    dev_res = first_failed_filter(good(dev_pct=dev), P)
    assert base_res == dev_res
    assert candidate_status(good(), P, NO) == candidate_status(good(dev_pct=dev), P, NO)
