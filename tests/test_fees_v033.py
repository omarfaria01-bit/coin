"""v0.3.3 fee routing (§10) and the pad.json fields it needs (§15)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from adapters.config_loader import load_pad
from engine.fees import route_v033
from engine.params import FeeParams, PadParams

_P = FeeParams()


def test_default_split_and_dust_to_holder_pot() -> None:
    assert route_v033(100, _P) == {"dev": 25, "holder_pot": 35, "draw_pot": 25, "buyback_burn": 15}
    assert route_v033(3, _P) == {"dev": 0, "holder_pot": 3, "draw_pot": 0, "buyback_burn": 0}
    assert route_v033(0, _P) == {"dev": 0, "holder_pot": 0, "draw_pot": 0, "buyback_burn": 0}


def test_disabled_draws_send_their_share_to_the_holder_pot() -> None:
    assert route_v033(100, _P, draws_disabled=True) == {
        "dev": 25,
        "holder_pot": 60,
        "draw_pot": 0,
        "buyback_burn": 15,
    }


def test_rejects_bad_amounts() -> None:
    with pytest.raises(ValueError, match="amount"):
        route_v033(-1, _P)
    with pytest.raises(TypeError):
        route_v033(1.0, _P)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        route_v033(True, _P)  # type: ignore[arg-type]


@given(st.integers(0, 10**18), st.booleans())
@settings(max_examples=200, deadline=None)
def test_property_conservation_and_floors(amount: int, disabled: bool) -> None:
    out = route_v033(amount, _P, draws_disabled=disabled)
    assert sum(out.values()) == amount and min(out.values()) >= 0
    assert out["dev"] == amount * 25 // 100 and out["buyback_burn"] == amount * 15 // 100
    assert out["draw_pot"] == (0 if disabled else amount * 25 // 100)


def test_pad_v033_fields() -> None:
    pad = load_pad()
    assert pad.quote_asset == "SOL" and pad.burn_allowed is None
    assert pad.price_source.pool_type is None and pad.price_source.reserve_accounts == ()
    filled = PadParams(price_source={"pool_type": "cpmm", "reserve_accounts": ["r1", "r2"]})
    assert filled.price_source.reserve_accounts == ("r1", "r2")
    with pytest.raises(ValidationError):
        PadParams(price_source={"pool_type": "orderbook"})
