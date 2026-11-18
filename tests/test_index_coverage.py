from fractions import Fraction

import pytest

from sim.index_coverage import MISS_RATES, hours_to_eligible, render

HALF = Fraction(1, 2)


def test_no_misses_is_half_window() -> None:
    assert hours_to_eligible(5, Fraction(0), HALF) == 12
    assert hours_to_eligible(15, Fraction(0), HALF) == 12


def test_known_values() -> None:
    assert hours_to_eligible(5, Fraction(1, 10), HALF) == Fraction(40, 3)  # 144/0.9=160 slots
    assert hours_to_eligible(5, Fraction(3, 10), HALF) == Fraction(206 * 5, 60)


def test_monotone_in_miss_rate_and_coverage() -> None:
    for iv in (5, 10, 15):
        vals = [hours_to_eligible(iv, Fraction(i, 20), HALF) for i in range(0, 10)]
        assert all(v is not None for v in vals)
        assert vals == sorted(vals)  # type: ignore[type-var]
    covs = [hours_to_eligible(5, Fraction(1, 10), Fraction(i, 10)) for i in range(0, 8)]
    assert covs == sorted(covs)  # type: ignore[type-var]


def test_edges() -> None:
    assert hours_to_eligible(5, Fraction(1), HALF) is None
    assert hours_to_eligible(5, Fraction(1), Fraction(0)) == 0
    assert hours_to_eligible(5, Fraction(0), Fraction(1)) == 24
    assert hours_to_eligible(5, Fraction(1, 10), Fraction(1)) is None  # would need > window


def test_validation() -> None:
    with pytest.raises(ValueError):
        hours_to_eligible(0, Fraction(0), HALF)
    with pytest.raises(ValueError):
        hours_to_eligible(5, Fraction(3, 2), HALF)
    with pytest.raises(ValueError):
        hours_to_eligible(5, Fraction(0), Fraction(2))


def test_render_deterministic() -> None:
    assert render(HALF, 24, 5) == render(HALF, 24, 5)
    assert len(MISS_RATES) == 3
