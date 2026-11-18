"""Hypothesis properties for F11 and F8c in ``first_failed_filter`` (#206).

F11 compares market cap to liquidity with exact ``Fraction`` arithmetic; F8c accepts Token-2022
only when the mint's extension set is a subset of the allowlist. Only tests change here.
"""

from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import base58
from hypothesis import given, settings
from hypothesis import strategies as st

from index.filters import MISSING, SPL_TOKEN, TOKEN_2022, Metrics, first_failed_filter
from index.params import FILTER_CODES, IndexParams

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))


def mint(i: int) -> str:
    return base58.b58encode(bytes([i % 256]) * 32).decode()


def good(i: int = 1, **kw: object) -> Metrics:
    """Baseline coin that passes every filter; ``kw`` overrides individual metrics."""
    base = Metrics(
        mint=mint(i),
        ticker="GTA6",
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
        token_program=SPL_TOKEN,
        extensions=(),
        unique_traders=900,
        volume_usd=600_000.0,
        independent_traders=900,
        roundtrip_share=0.0,
        volume_wallets=100,
        median_trade_sol=0.1,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ Property A: F11 (#167)


@st.composite
def liq_mc(draw):
    """Liquidity above F2's floor plus a market cap, biased to the exact 100x boundary."""
    liq = draw(st.floats(min_value=50_000, max_value=1e9, allow_nan=False, allow_infinity=False))
    mode = draw(st.sampled_from(["random", "at", "over", "under"]))
    if mode == "random":
        mc = draw(st.floats(min_value=1, max_value=1e12, allow_nan=False, allow_infinity=False))
    elif mode == "at":
        mc = float(100 * liq)
    elif mode == "over":
        mc = float(100 * liq) * (1 + 1e-9)
    else:
        mc = float(100 * liq) * (1 - 1e-9)
    return liq, mc


@settings(max_examples=50)
@given(liq_mc())
def test_f11_fails_iff_mc_exceeds_ratio_times_liquidity(case: tuple[float, float]) -> None:
    liq, mc = case
    # Turnover stays exactly 1 (inside the band) so only F11 can decide the outcome.
    m = good(liquidity_usd=liq, mc_usd=mc, volume_usd=mc)
    expected = Fraction(mc) > Fraction(P.filters.max_mc_liquidity_ratio) * Fraction(liq)
    assert first_failed_filter(m, P) == ("F11" if expected else None)


# ------------------------------------------------------------------ Property B: F8c (#171, D32)

OUTSIDE = ("permanentDelegate", "transferHook", "transferFeeConfig", "pausableConfig", "madeUpNew")


@settings(max_examples=50)
@given(
    st.sets(st.sampled_from(P.filters.token2022_allowed_extensions)),
    st.sampled_from(OUTSIDE),
)
def test_f8c_accepts_exactly_the_allowlist_subsets(allowed: set[str], outside: str) -> None:
    assert outside not in P.filters.token2022_allowed_extensions
    extensions = tuple(sorted(allowed))
    assert first_failed_filter(good(token_program=TOKEN_2022, extensions=extensions), P) is None
    assert (
        first_failed_filter(good(token_program=TOKEN_2022, extensions=(*extensions, outside)), P)
        == "F8"
    )


# ------------------------------------------------------------------ Property C: totality


NUM = st.none() | st.floats(allow_nan=False, allow_infinity=False)
INT = st.none() | st.integers(-(10**9), 10**9)
BOOL = st.none() | st.booleans()

ANY_METRICS = st.builds(
    Metrics,
    mint=st.text(),
    ticker=st.text(),
    name=st.text(),
    description=st.text(),
    coverage=NUM,
    age_hours=NUM,
    liquidity_usd=NUM,
    mc_usd=NUM,
    top10_pct=NUM,
    total_fees_sol=NUM,
    window_fees_sol=NUM,
    bundle_pct=NUM,
    dev_pct=NUM,
    creator_launches_7d=INT,
    mint_authority_revoked=BOOL,
    freeze_authority_revoked=BOOL,
    token_program=st.none() | st.sampled_from((SPL_TOKEN, TOKEN_2022, "Other111")),
    extensions=st.none() | st.lists(st.text(), max_size=3).map(tuple),
    unique_traders=INT,
    volume_usd=NUM,
    independent_traders=INT,
    roundtrip_share=NUM,
    volume_wallets=INT,
    median_trade_sol=NUM,
)

ALLOWED = set(FILTER_CODES) | {None, MISSING}


@settings(max_examples=50)
@given(ANY_METRICS)
def test_first_failed_filter_is_deterministic_and_total(m: Metrics) -> None:
    first = first_failed_filter(m, P)
    assert first == first_failed_filter(m, P)
    assert first in ALLOWED
