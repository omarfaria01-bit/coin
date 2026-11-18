"""Hypothesis properties for ``emergency_reason`` (D34, #172) and F9/F10 (D33, #170).

Emergency: a liquidity drop must show on the current AND the earlier sample; rug flag and enabled
authorities remove a member immediately and never look at ``earlier``. F9/F10: independent-trader
floor, round-trip share bounds, wallet breadth. Only tests change here; ``index/`` is untouched.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import base58
from hypothesis import given
from hypothesis import strategies as st

from index.filters import MISSING, SPL_TOKEN, Metrics, first_failed_filter
from index.params import IndexParams, frac
from index.select import emergency_reason

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
LIMIT = float(frac(P.emergency.liquidity_drop_pct_1h))  # 50

Pair = tuple[float | None, float | None]

# ------------------------------------------------------------------ strategies

ago_values = st.floats(min_value=1.0, max_value=1e9, allow_nan=False, allow_infinity=False)


@st.composite
def dropped_pair(draw) -> Pair:
    """(now, 1h ago) with a drop clearly at or above the limit (away from float edges)."""
    ago = draw(ago_values)
    pct = draw(st.floats(min_value=LIMIT + 0.01, max_value=100.0))
    return ago * (1 - pct / 100), ago


@st.composite
def not_dropped_pair(draw) -> Pair:
    """A pair that does not count as a drop: small/negative drop, or missing/zero data."""
    kind = draw(st.sampled_from(["small", "rise", "now_none", "ago_none", "ago_zero"]))
    ago = draw(ago_values)
    if kind == "small":
        pct = draw(st.floats(min_value=0.0, max_value=LIMIT - 0.01))
        return ago * (1 - pct / 100), ago
    if kind == "rise":
        return ago * draw(st.floats(min_value=1.0, max_value=10.0)), ago
    if kind == "now_none":
        return None, ago
    if kind == "ago_none":
        return ago, None
    return ago, 0.0


any_pair = st.one_of(dropped_pair(), not_dropped_pair())
maybe_earlier = st.one_of(st.none(), any_pair)
clean_authority = st.sampled_from([True, None])
any_authority = st.sampled_from([True, False, None])


def reason(current: Pair, earlier: Pair | None, **kw) -> str | None:
    args = {"mint": True, "freeze": True, "rug": False} | kw
    return emergency_reason(
        current[0], current[1], args["mint"], args["freeze"], args["rug"], P, earlier=earlier
    )


# ------------------------------------------------------------------ two-sample debounce


@given(current=dropped_pair(), earlier=not_dropped_pair())
def test_drop_now_but_not_earlier_is_none(current: Pair, earlier: Pair) -> None:
    assert reason(current, earlier) is None


@given(current=dropped_pair(), earlier=dropped_pair())
def test_drop_on_both_samples_is_liquidity_drop(current: Pair, earlier: Pair) -> None:
    assert reason(current, earlier) == "liquidity_drop"


@given(current=dropped_pair())
def test_drop_without_earlier_sample_still_fires(current: Pair) -> None:
    """earlier=None keeps the single-sample rule (callers without history)."""
    assert reason(current, None) == "liquidity_drop"


@given(current=not_dropped_pair(), earlier=maybe_earlier)
def test_no_drop_now_is_never_liquidity_drop(current: Pair, earlier: Pair | None) -> None:
    assert reason(current, earlier) is None


@given(current=any_pair, earlier=any_pair)
def test_earlier_can_only_suppress_never_create(current: Pair, earlier: Pair) -> None:
    """With history the result is the single-sample result or None, never something new."""
    with_history = reason(current, earlier)
    assert with_history in (None, reason(current, None))


# ------------------------------------------------------------------ immediate reasons


@given(
    current=any_pair,
    earlier=maybe_earlier,
    mint=any_authority,
    freeze=any_authority,
)
def test_rug_flag_is_immediate_and_wins(current, earlier, mint, freeze) -> None:
    assert reason(current, earlier, rug=True, mint=mint, freeze=freeze) == "rug_flag"


@given(
    current=any_pair,
    earlier=maybe_earlier,
    mint=any_authority,
    freeze=any_authority,
)
def test_authority_enabled_is_immediate(current, earlier, mint, freeze) -> None:
    if mint is False or freeze is False:
        assert reason(current, earlier, mint=mint, freeze=freeze) == "authority_enabled"


@given(
    current=any_pair,
    earlier_a=maybe_earlier,
    earlier_b=maybe_earlier,
    mint=any_authority,
    freeze=any_authority,
    rug=st.booleans(),
)
def test_result_ignores_earlier_when_rug_or_authority_trips(
    current, earlier_a, earlier_b, mint, freeze, rug
) -> None:
    if not (rug or mint is False or freeze is False):
        return
    a = reason(current, earlier_a, rug=rug, mint=mint, freeze=freeze)
    b = reason(current, earlier_b, rug=rug, mint=mint, freeze=freeze)
    assert a == b
    assert a == ("rug_flag" if rug else "authority_enabled")


@given(
    current=not_dropped_pair(), earlier=maybe_earlier, mint=clean_authority, freeze=clean_authority
)
def test_clean_member_without_drop_stays(current, earlier, mint, freeze) -> None:
    assert reason(current, earlier, mint=mint, freeze=freeze) is None


# ------------------------------------------------------------------ F9 / F10 (D33)


def mint_addr(i: int = 1) -> str:
    return base58.b58encode(bytes([i % 256]) * 32).decode()


def good(**kw: object) -> Metrics:
    """Baseline coin that passes every filter; ``kw`` overrides individual metrics."""
    base = Metrics(
        mint=mint_addr(),
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


def test_baseline_passes() -> None:
    assert first_failed_filter(good(), P) is None


@given(n=st.integers(min_value=0, max_value=5_000))
def test_f9_is_a_floor_on_independent_traders(n: int) -> None:
    got = first_failed_filter(good(independent_traders=n), P)
    assert got == ("F9" if n < P.filters.min_unique_traders else None)


@given(n=st.integers(min_value=0, max_value=5_000))
def test_f9_ignores_raw_unique_traders(n: int) -> None:
    """F9 reads independent_traders (D33), not the raw unique_traders count."""
    assert first_failed_filter(good(unique_traders=n), P) is None


def test_f9_missing_independent_traders_is_insufficient() -> None:
    assert first_failed_filter(good(independent_traders=None), P) == MISSING


@given(
    r=st.floats(min_value=0.0, max_value=1.0, allow_nan=False).filter(
        lambda r: abs(r - 0.875) > 1e-6
    )
)
def test_f10_roundtrip_share_removes_volume_from_turnover(r: float) -> None:
    """clean = volume*(1-r); with mc 1.5M, vol 600k turnover is 0.4*(1-r) >= 1/20 iff r <= 0.875."""
    got = first_failed_filter(good(roundtrip_share=r), P)
    assert got == ("F10" if r > 0.875 else None)


@given(r=st.one_of(st.floats(max_value=-1e-9), st.floats(min_value=1.0 + 1e-9)))
def test_f10_roundtrip_share_outside_unit_interval_is_missing(r: float) -> None:
    assert first_failed_filter(good(roundtrip_share=r), P) == MISSING


@given(w=st.integers(min_value=0, max_value=1_000))
def test_f10_needs_volume_wallet_breadth(w: int) -> None:
    got = first_failed_filter(good(volume_wallets=w), P)
    assert got == ("F10" if w < P.filters.min_volume_wallets else None)


@given(field=st.sampled_from(["roundtrip_share", "volume_wallets", "median_trade_sol"]))
def test_f10_missing_input_is_insufficient(field: str) -> None:
    assert first_failed_filter(good(**{field: None}), P) == MISSING
