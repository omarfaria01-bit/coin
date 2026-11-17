"""index/filters.py: universe, filters F1–F10, score and ranking (INDEX_RULES §1–§4, #156)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import base58
import pytest
from hypothesis import given
from hypothesis import strategies as st

from index.filters import (
    Metrics,
    candidate_status,
    first_failed_filter,
    keyword_hit,
    log_score,
    rank,
)
from index.params import IndexParams, OverrideEntry, Overrides

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
        window_fees_sol=12.0,
        bundle_pct=3.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        unique_traders=900,
        volume_usd=600_000.0,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ §1


@pytest.mark.parametrize(
    ("text", "kw", "hit"),
    [
        ("GTA6 to the moon", "GTA", True),
        ("$GTA", "GTA", True),
        ("AGTAB", "GTA", False),
        ("VIBE coin", "VI", False),
        ("GTA VI", "VI", True),
        ("vice   city", "Vice City", True),
        ("Leonida", "leonida", True),
    ],
)
def test_keyword_boundaries(text: str, kw: str, hit: bool) -> None:
    assert keyword_hit(text, kw) is hit


def test_candidate_status() -> None:
    m = good()
    assert candidate_status(m, P, NO) is None
    weak = replace(m, ticker="LUCIA", name="Lucia", description="")
    assert candidate_status(weak, P, NO) == "weak_keyword"
    allow = Overrides(allow=(OverrideEntry(mint=weak.mint, reason="GTA 6 heroine", issue=156),))
    assert candidate_status(weak, P, allow) is None
    deny = Overrides(deny=(OverrideEntry(mint=m.mint, reason="impersonator", issue=156),))
    assert candidate_status(m, P, deny) == "denied"
    me = P.model_copy(update={"self_mint": m.mint})
    assert candidate_status(m, me, NO) == "self"
    assert candidate_status(replace(m, ticker="DOG", name="Dog", description=""), P, NO) == (
        "no_keyword"
    )


# ------------------------------------------------------------------ §3


def test_good_coin_passes() -> None:
    assert first_failed_filter(good(), P) is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"coverage": 0.49}, "insufficient_data"),
        ({"age_hours": 5.9}, "F1"),
        ({"liquidity_usd": 49_999.0}, "F2"),
        ({"top10_pct": 12.99}, "F3"),
        ({"top10_pct": 27.01}, "F3"),
        ({"total_fees_sol": 9.99}, "F4"),
        ({"bundle_pct": 10.01}, "F5"),
        ({"dev_pct": 5.01}, "F6"),
        ({"creator_launches_7d": 4}, "F7"),
        ({"freeze_authority_revoked": False}, "F8"),
        ({"unique_traders": 199}, "F9"),
        ({"volume_usd": 1_500_000.0 * 0.049}, "F10"),
        ({"volume_usd": 1_500_000.0 * 3.01}, "F10"),
        ({"total_fees_sol": None}, "insufficient_data"),
    ],
)
def test_each_filter_fails(change: dict, code: str) -> None:
    assert first_failed_filter(good(**change), P) == code


@pytest.mark.parametrize(
    "change",
    [
        {"top10_pct": 13.0},
        {"top10_pct": 27.0},
        {"total_fees_sol": 10.0},
        {"liquidity_usd": 50_000.0},
        {"unique_traders": 200},
        {"volume_usd": 1_500_000.0 * 3},
    ],
)
def test_boundaries_pass(change: dict) -> None:
    assert first_failed_filter(good(**change), P) is None


def test_dry_run_skip_lets_missing_fees_through() -> None:
    dry = P.model_copy(update={"dry_run": P.dry_run.model_copy(update={"skip_filters": ("F4",)})})
    assert first_failed_filter(good(total_fees_sol=None), dry) is None
    assert first_failed_filter(good(total_fees_sol=None), P) == "insufficient_data"


# ------------------------------------------------------------------ §4


def test_score_needs_positive_inputs() -> None:
    assert log_score(good(window_fees_sol=None), P) is None
    assert log_score(good(), P) is not None


@given(
    st.lists(
        st.tuples(
            st.floats(1e4, 1e9), st.floats(5e4, 1e7), st.floats(1, 1e4), st.integers(200, 10**5)
        ),
        min_size=2,
        max_size=12,
    ),
    st.floats(0.01, 100),
)
def test_ranking_unchanged_by_unit_scaling(rows: list, k: float) -> None:
    coins = [
        good(i, mc_usd=mc, liquidity_usd=liq, window_fees_sol=fe, unique_traders=tr)
        for i, (mc, liq, fe, tr) in enumerate(rows)
    ]
    a = {c.mint: log_score(c, P) for c in coins}
    b = {
        c.mint: log_score(replace(c, mc_usd=c.mc_usd * k, liquidity_usd=c.liquidity_usd * k), P)
        for c in coins
    }
    ra, rb = rank(a), rank(b)  # type: ignore[arg-type]
    # Scaling shifts every log S by the same amount; only rounding at 12 decimals can swap
    # near-ties, so compare the coins whose scores differ by more than the rounding step.
    for x, y in zip(ra, ra[1:], strict=False):
        if abs(a[x] - a[y]) > 1e-9:  # type: ignore[operator]
            assert rb.index(x) < rb.index(y)


def test_rank_ties_broken_by_mint_bytes() -> None:
    scores = {mint(9): 1.0, mint(3): 1.0, mint(5): 2.0}
    assert rank(scores) == [mint(5), mint(3), mint(9)]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("key", ["liquidity_usd", "top10_pct", "total_fees_sol", "dev_pct"])
def test_non_finite_metrics_fail_safe(key: str, bad: float) -> None:
    assert first_failed_filter(good(**{key: bad}), P) == "insufficient_data"


def test_lifetime_fee_measure_is_global() -> None:
    life = P.model_copy(
        update={"score": P.score.model_copy(update={"score_fees_window": "lifetime"})}
    )
    m = good(window_fees_sol=None)
    assert log_score(m, P) is None  # window measure chosen, missing -> excluded
    assert log_score(m, life) is not None
    assert log_score(good(window_fees_sol=float("nan")), P) is None
