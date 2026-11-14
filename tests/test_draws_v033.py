"""Tests for v0.3.3 draw weights and rejection sampling (COIN_MATH §9)."""

from __future__ import annotations

from fractions import Fraction
from hashlib import sha256

from engine.draws import (
    _TWO256,
    DELTA_DEFAULT,
    DRAW_PERIOD_EPOCHS_DEFAULT,
    DRAW_STREAM_PREFIX,
    DRAWS_ENABLED_DEFAULT,
    MIN_DRAW_SHARE_DEFAULT,
    TREASURY_ENABLED_DEFAULT,
    accept_draw_uniform,
    draw_stream_int,
    draw_weight,
    is_draw_eligible,
    isqrt,
    min_eligible_epochs,
    sample_draw_winners,
)

ZERO = bytes(32)
ONE = bytes([1]) * 32


def test_defaults_and_period_variants() -> None:
    assert DRAWS_ENABLED_DEFAULT is False
    assert TREASURY_ENABLED_DEFAULT is False
    assert DRAW_PERIOD_EPOCHS_DEFAULT == 7
    assert DELTA_DEFAULT == 1
    assert Fraction(1, 100_000) == MIN_DRAW_SHARE_DEFAULT
    assert min_eligible_epochs() == 5
    assert min_eligible_epochs(1) == 1
    assert min_eligible_epochs(3) == 3
    assert min_eligible_epochs(7) == 5


def test_isqrt_weights_and_eligibility() -> None:
    assert [isqrt(n) for n in (0, 1, 2, 3, 4, 8, 9, 10**12)] == [
        0,
        1,
        1,
        1,
        2,
        2,
        3,
        10**6,
    ]
    assert isqrt((1 << 128) - 1) ** 2 <= (1 << 128) - 1
    assert draw_weight(0) == 0
    assert draw_weight(99) == 9
    assert draw_weight(Fraction(99, 1)) == 9
    assert draw_weight(Fraction(199, 2)) == 9  # floor(99.5) = 99
    supply = 1_000_000
    # floor is 10 tokens at the default 1/100_000 of 1M.
    assert is_draw_eligible(5, 7, 10, supply) is True
    assert is_draw_eligible(5, 7, 9, supply) is False
    assert is_draw_eligible(4, 7, 10, supply) is False
    assert is_draw_eligible(5, 7, 10, supply, forfeited=True) is False
    assert is_draw_eligible(1, 1, 10, supply) is True


def test_rejection_sampling_and_stream_determinism() -> None:
    # Unbiased range: reject x in [floor(2^256/W)·W, 2^256).
    w = 3
    limit = (_TWO256 // w) * w
    assert accept_draw_uniform(limit - 1, w) == (limit - 1) % w
    assert accept_draw_uniform(limit, w) is None
    assert accept_draw_uniform(_TWO256 - 1, w) is None
    assert accept_draw_uniform(0, w) == 0
    assert accept_draw_uniform(4, 3) == 1
    x = draw_stream_int(ZERO, ONE, 0, ZERO, ONE, 0)
    assert 0 <= x < _TWO256
    assert draw_stream_int(ZERO, ONE, 0, ZERO, ONE, 0) == x
    expect = int.from_bytes(
        sha256(
            DRAW_STREAM_PREFIX
            + ZERO
            + ONE
            + (0).to_bytes(8, "big")
            + ZERO
            + ONE
            + (0).to_bytes(8, "big")
        ).digest(),
        "big",
    )
    assert x == expect
    assert draw_stream_int(ZERO, ONE, 0, ZERO, ONE, 1) != x


def test_sampler_is_deterministic_without_replacement() -> None:
    weights = {"C": 1, "A": 2, "B": 1}
    kwargs = dict(
        genesis_hash=ZERO,
        mint=ONE,
        draw_index=7,
        snapshot_hash=ZERO,
        rho=ONE,
        k=3,
    )
    first = sample_draw_winners(weights, **kwargs)
    assert first == sample_draw_winners(weights, **kwargs)
    assert len(first) == 3 and len(set(first)) == 3
    assert set(first) == {"A", "B", "C"}
    # k larger than the eligible set just returns everyone once.
    assert set(sample_draw_winners(weights, **{**kwargs, "k": 10})) == {"A", "B", "C"}
    assert sample_draw_winners({"A": 0, "B": 0}, **kwargs) == []
