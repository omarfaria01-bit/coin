"""Creator-fee routing (COIN_MATH §10). Owner: Claude."""

from __future__ import annotations

from engine.params import FeeParams


def route(amount_lamports: int, p: FeeParams) -> dict[str, int]:
    """Split by shares with floor; rounding dust goes to holder_pot. Σ == amount."""
    raise NotImplementedError
