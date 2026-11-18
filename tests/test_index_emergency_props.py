"""Hypothesis properties for ``emergency_reason``: two-sample debounce and immediate reasons (#209).

D34 (#172) debounces liquidity removals: a drop of at least ``liquidity_drop_pct_1h`` must show on
the current sample *and* on the previous one (``earlier``, 15 min apart). A drop on one sample
only, a missing/zero 1h-ago value, or missing earlier data does not remove a member. A rug flag or
a re-enabled mint/freeze authority is immediate and must not depend on ``earlier`` at all (§5).

Only this test file changes; ``index/`` is untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from index.params import IndexParams, frac
from index.select import emergency_reason

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
LIMIT = float(frac(P.emergency.liquidity_drop_pct_1h))
REASONS = {None, "rug_flag", "authority_enabled", "liquidity_drop"}

POS = st.floats(min_value=1e3, max_value=1e12, allow_nan=False, allow_infinity=False)
ANY = st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False)
PAIR = tuple[float | None, float | None]

# Comfortably on each side of LIMIT, so float rounding can never flip the decision.
DROP = st.sampled_from([62.5, 75.0, 87.5])
NO_DROP = st.sampled_from([0.0, 10.0, 25.0, 40.0])


@st.composite
def samples(draw, drop_pct):
    """(liquidity now, liquidity 1h ago) showing exactly ``drop_pct`` down."""
    ago = draw(POS)
    pct = draw(drop_pct)
    return ago * (1 - pct / 100), ago


@st.composite
def unconfirmed_earlier(draw) -> PAIR:
    """A supplied previous sample that does *not* confirm a drop."""
    kind = draw(st.sampled_from(("missing_prev", "missing_now", "zero_ago", "small", "flat")))
    now = draw(ANY)
    ago = draw(POS)
    if kind == "missing_prev":
        return now, None
    if kind == "missing_now":
        return None, ago
    if kind == "zero_ago":
        return now, 0.0
    if kind == "small":
        return ago * (1 - draw(st.floats(0, 49.9)) / 100), ago
    return ago, ago


@st.composite
def any_earlier(draw) -> PAIR | None:
    """Any ``earlier`` value a caller might pass, including none at all."""
    return draw(st.none() | samples(DROP) | samples(NO_DROP) | unconfirmed_earlier())


# ------------------------------------------------------------------ two-sample debounce (D34)


@settings(max_examples=100)
@given(samples(DROP), unconfirmed_earlier())
def test_current_drop_alone_does_not_remove(current: tuple[float, float], earlier: PAIR) -> None:
    """A drop on the current sample but not on the earlier one removes nothing."""
    now, ago = current
    assert emergency_reason(now, ago, True, True, False, P, earlier) is None


@settings(max_examples=100)
@given(samples(DROP), samples(DROP))
def test_drop_on_both_samples_removes(
    current: tuple[float, float], earlier: tuple[float, float]
) -> None:
    """A drop confirmed by the previous sample removes for ``liquidity_drop``."""
    now, ago = current
    assert emergency_reason(now, ago, True, True, False, P, earlier) == "liquidity_drop"


def test_limit_is_inclusive_on_both_samples() -> None:
    at_limit = (100.0 - LIMIT, 100.0)
    assert emergency_reason(*at_limit, True, True, False, P, at_limit) == "liquidity_drop"
    just_under = (100.0 - LIMIT + 1e-6, 100.0)
    assert emergency_reason(*just_under, True, True, False, P, at_limit) is None


def test_no_earlier_sample_supplied_leaves_the_current_drop_standing() -> None:
    """``earlier=None`` means the caller has no previous sample; the current drop stands."""
    assert emergency_reason(50.0, 100.0, True, True, False, P) == "liquidity_drop"


# ------------------------------------------------------------------ immediate reasons (§5)


@settings(max_examples=100)
@given(
    st.booleans(),  # rug flag
    st.sampled_from((True, False, None)),  # mint authority revoked
    st.sampled_from((True, False, None)),  # freeze authority revoked
    st.none() | ANY,  # liquidity now
    st.none() | ANY,  # liquidity 1h ago
    any_earlier(),
    any_earlier(),
)
def test_immediate_reasons_ignore_the_earlier_sample(
    rug: bool,
    mint_revoked: bool | None,
    freeze_revoked: bool | None,
    now: float | None,
    ago: float | None,
    first: PAIR | None,
    second: PAIR | None,
) -> None:
    """Rug flag and re-enabled authorities never depend on ``earlier`` (rug flag wins)."""
    if not (rug or mint_revoked is False or freeze_revoked is False):
        return
    expected = "rug_flag" if rug else "authority_enabled"
    assert emergency_reason(now, ago, mint_revoked, freeze_revoked, rug, P, None) == expected
    assert emergency_reason(now, ago, mint_revoked, freeze_revoked, rug, P, first) == expected
    assert emergency_reason(now, ago, mint_revoked, freeze_revoked, rug, P, second) == expected


# ------------------------------------------------------------------ totality and safety


@settings(max_examples=100)
@given(
    st.none() | ANY,
    st.none() | ANY,
    st.sampled_from((True, False, None)),
    st.sampled_from((True, False, None)),
    st.booleans(),
    any_earlier(),
)
def test_result_is_total_and_liquidity_drop_needs_a_current_drop(
    now: float | None,
    ago: float | None,
    mint_revoked: bool | None,
    freeze_revoked: bool | None,
    rug: bool,
    earlier: PAIR | None,
) -> None:
    reason = emergency_reason(now, ago, mint_revoked, freeze_revoked, rug, P, earlier)
    assert reason in REASONS
    assert reason == emergency_reason(now, ago, mint_revoked, freeze_revoked, rug, P, earlier)
    if reason == "liquidity_drop":
        # Necessary condition: the current sample itself must show the drop.
        assert now is not None and ago
        assert (ago - now) / ago * 100 >= LIMIT
