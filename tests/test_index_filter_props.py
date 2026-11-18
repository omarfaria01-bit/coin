"""Property tests for F11 and F8c in index/filters.first_failed_filter (#206).

Only tests change here; ``index/`` is untouched. F2 runs before F11, so liquidity is drawn at or
above ``min_liquidity_usd``; volume is tied to mc so turnover (F10) stays in band.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from index.filters import SPL_TOKEN, TOKEN_2022, Metrics, first_failed_filter
from index.params import IndexParams
from tests.test_index_filters import good

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
assert P.dry_run.skip_filters == ()
ALLOWED = tuple(P.filters.token2022_allowed_extensions)
RATIO = Fraction(P.filters.max_mc_liquidity_ratio)
MIN_LIQ = float(P.filters.min_liquidity_usd)

liq = st.floats(min_value=MIN_LIQ, max_value=1e8, allow_nan=False, allow_infinity=False)


@st.composite
def liq_and_mc(draw: st.DrawFn) -> tuple[float, float]:
    """Liquidity plus an mc that is on, just around, or far from the F11 boundary."""
    lq = draw(liq)
    edge = float(RATIO * Fraction(lq))
    mc = draw(
        st.one_of(
            st.just(edge),
            st.just(math.nextafter(edge, math.inf)),
            st.just(math.nextafter(edge, 0.0)),
            st.floats(min_value=1.0, max_value=edge * 3, allow_nan=False, allow_infinity=False),
        )
    )
    return lq, mc


@given(liq_and_mc())
def test_f11_fails_iff_mc_exceeds_ratio_times_liquidity(pair: tuple[float, float]) -> None:
    lq, mc = pair
    m = good(liquidity_usd=lq, mc_usd=mc, volume_usd=mc / 2)
    expected = "F11" if Fraction(mc) > RATIO * Fraction(lq) else None
    assert first_failed_filter(m, P) == expected


@given(st.lists(st.sampled_from(ALLOWED), max_size=len(ALLOWED) * 2).map(tuple))
def test_f8c_allowlisted_extensions_pass(exts: tuple[str, ...]) -> None:
    assert first_failed_filter(good(token_program=TOKEN_2022, extensions=exts), P) is None


@given(
    st.lists(st.sampled_from(ALLOWED), max_size=len(ALLOWED)).map(tuple),
    st.text(min_size=1, max_size=20).filter(lambda s: s not in ALLOWED),
)
def test_f8c_extension_outside_allowlist_fails_f8(exts: tuple[str, ...], extra: str) -> None:
    m = good(token_program=TOKEN_2022, extensions=(*exts, extra))
    assert first_failed_filter(m, P) == "F8"


fin = st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False)
opt = st.one_of(st.none(), fin)
opt_int = st.one_of(st.none(), st.integers(min_value=-5, max_value=10_000))
opt_bool = st.one_of(st.none(), st.booleans())

metrics = st.builds(
    Metrics,
    mint=st.just("m"),
    ticker=st.just("GTA"),
    coverage=st.one_of(st.none(), st.floats(min_value=-1, max_value=2)),
    age_hours=opt,
    liquidity_usd=opt,
    mc_usd=opt,
    top10_pct=opt,
    total_fees_sol=opt,
    window_fees_sol=opt,
    bundle_pct=opt,
    dev_pct=opt,
    creator_launches_7d=opt_int,
    mint_authority_revoked=opt_bool,
    freeze_authority_revoked=opt_bool,
    token_program=st.one_of(
        st.none(), st.sampled_from([SPL_TOKEN, TOKEN_2022]), st.text(max_size=8)
    ),
    extensions=st.one_of(st.none(), st.lists(st.text(max_size=8), max_size=3).map(tuple)),
    unique_traders=opt_int,
    volume_usd=opt,
)


@given(metrics)
def test_first_failed_filter_total_and_deterministic(m: Metrics) -> None:
    a = first_failed_filter(m, P)
    assert a == first_failed_filter(m, P)
    assert a is None or a == "insufficient_data" or a in {f"F{i}" for i in range(1, 12)}
