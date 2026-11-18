"""Fee router conserves lamports and sends dust to holder_pot (COIN_MATH §10)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from engine.fees import route
from engine.params import FeeParams

_KEYS = ("dev", "holder_pot", "draw_pot", "buyback_burn")
_DEFAULT = FeeParams(dev=0.25, holder_pot=0.35, draw_pot=0.25, buyback_burn=0.15)  # mechanics


def test_d28_defaults_70_30_no_team_no_buyback() -> None:
    assert route(100, FeeParams()) == {
        "dev": 0,
        "holder_pot": 70,
        "draw_pot": 30,
        "buyback_burn": 0,
    }


def test_default_split_and_dust_goes_to_holder_pot() -> None:
    out = route(100, _DEFAULT)
    assert list(out) == list(_KEYS)
    assert out == {"dev": 25, "holder_pot": 35, "draw_pot": 25, "buyback_burn": 15}
    # 1 lamport cannot be split; the whole unit is dust to holder_pot.
    out = route(1, _DEFAULT)
    assert out == {"dev": 0, "holder_pot": 1, "draw_pot": 0, "buyback_burn": 0}
    assert route(0, _DEFAULT) == {k: 0 for k in _KEYS}


def test_route_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="amount"):
        route(-1, _DEFAULT)


def test_fee_params_already_require_shares_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        FeeParams(dev=0.3)
    # Bypass pydantic so route's own 1e-9 guard is covered.
    broken = FeeParams.model_construct(dev=0.5, holder_pot=0.5, draw_pot=0.5, buyback_burn=0.5)
    with pytest.raises(ValueError, match="shares"):
        route(100, broken)


@given(st.integers(0, 10**24))
@settings(max_examples=80, deadline=None)
def test_route_conserves_amount(amount: int) -> None:
    out = route(amount, _DEFAULT)
    assert sum(out.values()) == amount
    assert set(out) == set(_KEYS)
    # Large pots stay exact (no float product).
    assert out["dev"] == amount * 25 // 100
    assert out["draw_pot"] == amount * 25 // 100
    assert out["buyback_burn"] == amount * 15 // 100
    assert out["holder_pot"] == amount - (out["dev"] + out["draw_pot"] + out["buyback_burn"])
