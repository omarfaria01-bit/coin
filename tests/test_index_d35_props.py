"""Hypothesis properties pinning kiwi's 18 Nov rules (D35, INDEX_RULES §1-§3) (#239).

35 keywords, F1 = 4h, F4 = 8 SOL, F5 = 30%, F10 = volume > 0, coverage 0/None = insufficient_data,
dev_pct is data only. Only tests change here.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import base58
from hypothesis import given
from hypothesis import strategies as st

from index.filters import (
    MISSING,
    SPL_TOKEN,
    Metrics,
    candidate_status,
    first_failed_filter,
    keyword_hit,
)
from index.params import IndexParams, Overrides

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
NO = Overrides()
KEYWORDS = tuple(P.keywords.strong)
LETTERS = st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
NON_LETTERS = st.text(alphabet=" 0123456789.,;:!?-_/()[]#$@\n\t", max_size=3)


def good(**kw: object) -> Metrics:
    """Baseline coin that passes every filter; ``kw`` overrides individual metrics."""
    base = Metrics(
        mint=base58.b58encode(bytes([1]) * 32).decode(),
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
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def as_name(text: str) -> Metrics:
    """Only the name carries the text, so ticker/description cannot match by accident."""
    return replace(good(), name=text, ticker="", description="")


def swap_case(s: str, mask: list[bool]) -> str:
    return "".join(c.upper() if mask[i % len(mask)] else c.lower() for i, c in enumerate(s))


def contains_other_keyword(kw: str) -> bool:
    return any(k != kw and keyword_hit(kw, k) for k in KEYWORDS)


ATOMIC = tuple(k for k in KEYWORDS if not contains_other_keyword(k))


# ------------------------------------------------------------------ (1) universe


def test_exactly_35_keywords_one_tier() -> None:
    assert len(KEYWORDS) == 35
    assert len(set(KEYWORDS)) == 35
    assert not hasattr(P.keywords, "weak")


@given(
    kw=st.sampled_from(KEYWORDS),
    pre=NON_LETTERS,
    post=NON_LETTERS,
    mask=st.lists(st.booleans(), min_size=1, max_size=8),
)
def test_keyword_wrapped_in_non_letters_any_case_is_candidate(
    kw: str, pre: str, post: str, mask: list[bool]
) -> None:
    text = pre + swap_case(kw, mask) + post
    assert candidate_status(as_name(text), P, NO) is None


@given(kw=st.sampled_from(ATOMIC), pre=NON_LETTERS, letter=LETTERS)
def test_letter_touching_left_is_not_candidate(kw: str, pre: str, letter: str) -> None:
    assert candidate_status(as_name(pre + letter + kw), P, NO) == "no_keyword"


@given(kw=st.sampled_from(ATOMIC), post=NON_LETTERS, letter=LETTERS)
def test_letter_touching_right_is_not_candidate(kw: str, post: str, letter: str) -> None:
    # Keywords containing a shorter keyword ("Lucia Caminos" -> "Lucia") are excluded: the
    # shorter one still matches when the letter touches only the longer one.
    assert candidate_status(as_name(kw + letter + post), P, NO) == "no_keyword"


@given(
    word=st.sampled_from(["VI", "Jason", "vi", "jason", "JASON", "Duval", "Cal", "Take", "Two"]),
    pre=NON_LETTERS,
    post=NON_LETTERS,
)
def test_bare_partial_words_never_match(word: str, pre: str, post: str) -> None:
    assert candidate_status(as_name(pre + word + post), P, NO) == "no_keyword"


# ------------------------------------------------------------------ (2) coverage


@given(cov=st.sampled_from([None, 0, 0.0, -0.0, -1.0]))
def test_zero_or_missing_coverage_is_insufficient_data(cov: float | None) -> None:
    assert first_failed_filter(good(coverage=cov), P) == MISSING


@given(cov=st.floats(min_value=1e-12, max_value=1.0, allow_nan=False))
def test_any_positive_coverage_passes(cov: float) -> None:
    assert first_failed_filter(good(coverage=cov), P) is None


# ------------------------------------------------------------------ (3) boundaries


@given(d=st.floats(min_value=0.001, max_value=100.0, allow_nan=False))
def test_f1_four_hours(d: float) -> None:
    assert first_failed_filter(good(age_hours=4.0), P) is None
    assert first_failed_filter(good(age_hours=4.0 + d), P) is None
    assert first_failed_filter(good(age_hours=max(4.0 - d, 0.0) if d < 4 else 0.0), P) == "F1"


@given(d=st.floats(min_value=0.001, max_value=100.0, allow_nan=False))
def test_f4_eight_sol(d: float) -> None:
    assert first_failed_filter(good(total_fees_sol=8.0), P) is None
    assert first_failed_filter(good(total_fees_sol=8.0 + d), P) is None
    assert first_failed_filter(good(total_fees_sol=max(8.0 - d, 0.0) if d < 8 else 0.0), P) == "F4"


@given(d=st.floats(min_value=0.001, max_value=70.0, allow_nan=False))
def test_f5_thirty_percent(d: float) -> None:
    assert first_failed_filter(good(bundle_pct=30.0), P) is None
    assert first_failed_filter(good(bundle_pct=max(30.0 - d, 0.0)), P) is None
    assert first_failed_filter(good(bundle_pct=30.0 + d), P) == "F5"


def test_exact_boundaries_and_ulp_neighbours() -> None:
    import math

    assert first_failed_filter(good(age_hours=math.nextafter(4.0, 0.0)), P) == "F1"
    assert first_failed_filter(good(total_fees_sol=math.nextafter(8.0, 0.0)), P) == "F4"
    assert first_failed_filter(good(bundle_pct=math.nextafter(30.0, 99.0)), P) == "F5"


# ------------------------------------------------------------------ (4) F10


@given(v=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
def test_f10_fails_for_nonpositive_volume(v: float) -> None:
    assert first_failed_filter(good(volume_usd=v), P) == "F10"


@given(v=st.floats(min_value=1e-9, max_value=1e12, allow_nan=False))
def test_f10_passes_for_any_positive_volume(v: float) -> None:
    assert first_failed_filter(good(volume_usd=v), P) is None


# ------------------------------------------------------------------ (5) dev_pct


@given(
    a=st.one_of(st.none(), st.floats(min_value=0, max_value=100, allow_nan=False)),
    b=st.one_of(st.none(), st.floats(min_value=0, max_value=100, allow_nan=False)),
    age=st.floats(min_value=0, max_value=100, allow_nan=False),
    fees=st.floats(min_value=0, max_value=100, allow_nan=False),
    bundle=st.floats(min_value=0, max_value=100, allow_nan=False),
    vol=st.floats(min_value=-10, max_value=100, allow_nan=False),
)
def test_dev_pct_never_changes_the_result(
    a: float | None, b: float | None, age: float, fees: float, bundle: float, vol: float
) -> None:
    kw = {"age_hours": age, "total_fees_sol": fees, "bundle_pct": bundle, "volume_usd": vol}
    assert first_failed_filter(good(dev_pct=a, **kw), P) == first_failed_filter(
        good(dev_pct=b, **kw), P
    )
