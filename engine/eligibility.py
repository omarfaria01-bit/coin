"""Price-free supply-share eligibility (COIN_MATH v0.3.3 §2). Owner: Grok."""

from __future__ import annotations

from fractions import Fraction

DEFAULT_MIN_ELIGIBLE_SHARE = Fraction(1, 1_000_000)


def parse_share(value: str | int | Fraction) -> Fraction:
    """Parse an exact rational share in [0, 1].

    Strings must be an integer or ``num/den`` (no decimal or scientific literals).
    """
    if isinstance(value, Fraction):
        share = value
    elif isinstance(value, bool):
        raise TypeError("share must be a rational, not bool")
    elif isinstance(value, int):
        share = Fraction(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or "." in text or "e" in text.lower() or " " in text:
            raise ValueError(f"share must be 'num/den' or an integer, got {value!r}")
        share = Fraction(text)
    else:
        raise TypeError(f"share must be str, int, or Fraction, got {type(value).__name__}")
    if share < 0 or share > 1:
        raise ValueError(f"share must be in [0, 1], got {share}")
    return share


def as_rational(value: int | Fraction | float) -> Fraction:
    """Exact rational for an integer, Fraction, or finite float bit-pattern."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("value must be a rational, not bool")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("value must be finite")
        num, den = value.as_integer_ratio()
        return Fraction(num, den)
    raise TypeError(f"value must be int, Fraction, or float, got {type(value).__name__}")


def eligibility_floor(
    total_supply: int, min_eligible_share: str | int | Fraction = DEFAULT_MIN_ELIGIBLE_SHARE
) -> Fraction:
    """``MIN_ELIGIBLE_SHARE · total supply``, in token base units (exact)."""
    if isinstance(total_supply, bool) or not isinstance(total_supply, int):
        raise TypeError("total_supply must be an int")
    if total_supply < 0:
        raise ValueError(f"total_supply must be >= 0, got {total_supply}")
    return parse_share(min_eligible_share) * total_supply


def is_eligible(
    twab: int | Fraction | float,
    total_supply: int,
    min_eligible_share: str | int | Fraction = DEFAULT_MIN_ELIGIBLE_SHARE,
) -> bool:
    """True iff ``B̄_c ≥ MIN_ELIGIBLE_SHARE · total supply``.

    No price or USD enters the comparison, and there is no separate hold gate
    (COIN_MATH §4 covers short holds). A current-engine float TWAB is accepted
    via its exact integer ratio. ``total_supply == 0`` makes the floor 0.
    """
    balance = as_rational(twab)
    if balance < 0:
        raise ValueError(f"twab must be >= 0, got {balance}")
    return balance >= eligibility_floor(total_supply, min_eligible_share)
