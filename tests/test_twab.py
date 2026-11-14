"""Tests for engine/twab.py (COIN_MATH §2, ENGINE_DESIGN §1)."""

from __future__ import annotations

from fractions import Fraction

from engine.twab import twab_exact


def test_twab_exact_is_a_fraction() -> None:
    changes = [(10, 3), (20, 0), (25, 7)]
    exact = twab_exact(0, changes, 0, 30)
    assert exact == Fraction(3 * 10 + 7 * 5, 30)
