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
    # D35: one tier. Former weak words and the new lore words are candidates; bare VI/Jason are not.
    for word in ("Lucia", "Rockstar", "Take-Two", "Vercetti", "Port Gellhorn", "Wasted"):
        hit = replace(m, ticker="X", name=word, description="")
        assert candidate_status(hit, P, NO) is None, word
    for word in ("VI", "Jason", "Lucian"):
        miss = replace(m, ticker="X", name=word, description="")
        assert candidate_status(miss, P, NO) == "no_keyword", word
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
        ({"coverage": 0.0}, "insufficient_data"),
        ({"coverage": None}, "insufficient_data"),
        ({"age_hours": 3.9}, "F1"),
        ({"liquidity_usd": 49_999.0}, "F2"),
        ({"top10_pct": 12.99}, "F3"),
        ({"top10_pct": 27.01}, "F3"),
        ({"total_fees_sol": 7.99}, "F4"),
        ({"bundle_pct": 30.01}, "F5"),
        ({"creator_launches_7d": 4}, "F7"),
        ({"freeze_authority_revoked": False}, "F8"),
        ({"independent_traders": 199}, "F9"),
        ({"independent_traders": None}, "insufficient_data"),
        ({"volume_usd": 0.0}, "F10"),
        ({"volume_usd": None}, "insufficient_data"),
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
        {"independent_traders": 200},
        {"coverage": 0.01},
        {"age_hours": 4.0},
        {"total_fees_sol": 8.0},
        {"bundle_pct": 30.0},
        {"dev_pct": 99.0},  # F6 removed (D35)
        {"roundtrip_share": 0.95, "volume_wallets": 1, "median_trade_sol": 0.0001},
        {"volume_usd": 1.0},
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
        good(
            i,
            mc_usd=mc,
            liquidity_usd=liq,
            window_fees_sol=fe,
            unique_traders=tr,
            independent_traders=tr,
        )
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


# ------------------------------------------------------------------ F11 (#167, D29)


def test_f11_mc_over_liquidity_boundary_is_exact() -> None:
    # liquidity 60k, ratio 100 -> MC 6,000,000 passes, one cent over fails. Turnover kept in band.
    ok = good(liquidity_usd=60_000.0, mc_usd=6_000_000.0, volume_usd=600_000.0)
    assert first_failed_filter(ok, P) is None
    bad = good(liquidity_usd=60_000.0, mc_usd=6_000_000.01, volume_usd=600_000.0)
    assert first_failed_filter(bad, P) == "F11"


def test_f11_low_float_replay_fails_and_legit_coin_unchanged() -> None:
    # The #167 replay: $50M MC on $50k liquidity (ratio 1000) used to rank first.
    float_coin = good(liquidity_usd=50_000.0, mc_usd=50_000_000.0, volume_usd=2_500_000.0)
    assert first_failed_filter(float_coin, P) == "F11"
    legit = good(liquidity_usd=150_000.0, mc_usd=2_000_000.0, volume_usd=300_000.0)
    assert first_failed_filter(legit, P) is None


def test_f11_missing_mc_is_insufficient_and_skip_works() -> None:
    assert first_failed_filter(good(mc_usd=None), P) == "insufficient_data"
    skipped = P.model_copy(
        update={"dry_run": P.dry_run.model_copy(update={"skip_filters": ("F11",)})}
    )
    float_coin = good(liquidity_usd=50_000.0, mc_usd=50_000_000.0, volume_usd=2_500_000.0)
    assert first_failed_filter(float_coin, skipped) is None


# ------------------------------------------------------------------ F8c (#171, D32)

T22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


@pytest.mark.parametrize(
    "ext",
    ["permanentDelegate", "transferHook", "transferFeeConfig", "pausableConfig", "madeUpNew"],
)
def test_f8c_dangerous_or_unknown_extension_fails(ext: str) -> None:
    assert first_failed_filter(good(token_program=T22, extensions=(ext,)), P) == "F8"
    assert (
        first_failed_filter(good(token_program=T22, extensions=("metadataPointer", ext)), P) == "F8"
    )


def test_f8c_allowlisted_t22_and_legacy_spl_pass() -> None:
    assert first_failed_filter(good(token_program=T22, extensions=("metadataPointer",)), P) is None
    assert first_failed_filter(good(), P) is None


def test_f8c_unknown_program_or_missing_data_fails_safe() -> None:
    assert first_failed_filter(good(token_program="Other111"), P) == "F8"
    assert first_failed_filter(good(token_program=None), P) == "insufficient_data"
    assert first_failed_filter(good(token_program=T22, extensions=None), P) == "insufficient_data"


def test_f8c_skip_works() -> None:
    skipped = P.model_copy(
        update={"dry_run": P.dry_run.model_copy(update={"skip_filters": ("F8",)})}
    )
    assert (
        first_failed_filter(good(token_program=T22, extensions=("permanentDelegate",)), skipped)
        is None
    )
