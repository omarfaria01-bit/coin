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


def route_v033(amount_q: int, p: FeeParams, *, draws_disabled: bool = False) -> dict[str, int]:
    """§10 split in exact integers: floor for dev, draw and burn; the holder pot gets
    its share plus all rounding dust, so ``Σ == amount_q``.

    ``draws_disabled``: draws are switched off as a feature (§10 last rule), so the
    draw share goes to the holder pot. Draws that are merely *not yet on* at launch
    (§16) keep accumulating in the draw pot: pass ``False`` for that case.
    """
    if isinstance(amount_q, bool) or not isinstance(amount_q, int):
        raise TypeError("amount_q must be an int (Q base units)")
    if amount_q < 0:
        raise ValueError(f"amount must be >= 0, got {amount_q}")
    shares = {key: Fraction(str(getattr(p, key))) for key in _KEYS}
    if sum(shares.values()) != 1:
        raise ValueError(f"fee shares must sum to exactly 1, got {sum(shares.values())}")
    out = {key: 0 for key in _KEYS}
    for key in ("dev", "draw_pot", "buyback_burn"):
        exact = shares[key] * amount_q
        out[key] = exact.numerator // exact.denominator
    if draws_disabled:
        out["draw_pot"] = 0
    out["holder_pot"] = amount_q - out["dev"] - out["draw_pot"] - out["buyback_burn"]
    return out
