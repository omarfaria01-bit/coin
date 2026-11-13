"""Weighted draw without replacement (COIN_MATH §9). Owner: Grok, from docs/ENGINE_DESIGN.md §5."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from engine.types import ClusterId


def uniform_from(randomness: bytes, cluster_id: ClusterId) -> float:
    """u_c in (0, 1) from sha256(randomness || cluster_id utf-8), first 8 bytes big-endian."""
    raise NotImplementedError


def draw_winners(scores: Mapping[ClusterId, float], randomness: bytes, k: int) -> list[ClusterId]:
    """Efraimidis-Spirakis with weight t_c = sqrt(s_c): top-k by ln(u_c)/t_c, ties by id."""
    raise NotImplementedError


def split_prizes(
    pot: int, winners: Sequence[ClusterId], prize_split: Sequence[float]
) -> tuple[dict[ClusterId, int], int]:
    """Rank i gets floor(pot·split[i]); unused ranks and dust stay in the pot (returned)."""
    raise NotImplementedError
