"""Creator-fee routing (COIN_MATH §10). Owner: Grok."""

from __future__ import annotations

from fractions import Fraction

from engine.params import FeeParams

_KEYS = ("dev", "holder_pot", "draw_pot", "buyback_burn")


def route(amount_lamports: int, p: FeeParams) -> dict[str, int]:
    """Split by shares with exact floor; rounding dust goes to holder_pot. Σ == amount."""
    if amount_lamports < 0:
        raise ValueError(f"amount must be >= 0, got {amount_lamports}")
    shares = {key: getattr(p, key) for key in _KEYS}
    if abs(sum(shares.values()) - 1.0) > 1e-9:
        raise ValueError(f"fee shares must sum to 1, got {sum(shares.values())}")
    paid = 0
    out: dict[str, int] = {}
    for key in _KEYS:
        if key == "holder_pot":
            continue
        amt = min(int(Fraction(str(shares[key])) * amount_lamports), amount_lamports - paid)
        out[key] = amt
        paid += amt
    out["holder_pot"] = amount_lamports - paid
    return {key: out[key] for key in _KEYS}
