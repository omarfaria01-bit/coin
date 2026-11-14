"""Weighted draw without replacement (COIN_MATH §9). Owner: Grok, from docs/ENGINE_DESIGN.md §5."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from hashlib import sha256

from engine.types import ClusterId

# Efraimidis–Spirakis A-Res in log-key form (IPL 2006; A-ExpJ uses the same keys).
# Uniforms are not a library RNG: ENGINE_DESIGN §5 requires
# u = (int.from_bytes(sha256(randomness || id)[:8], "big") + 0.5) / 2**64,
# so a third-party sampler cannot be called as-is. We adapt the standard key
# k = ln(u) / t and the top-k order, with ties broken by cluster id ascending.
_TWO64 = 1 << 64


def uniform_from(randomness: bytes, cluster_id: ClusterId) -> float:
    """u_c in (0, 1) from sha256(randomness || cluster_id utf-8), first 8 bytes big-endian."""
    digest = sha256(randomness + cluster_id.encode("utf-8")).digest()
    n = int.from_bytes(digest[:8], "big")
    return (n + 0.5) / _TWO64


def draw_winners(scores: Mapping[ClusterId, float], randomness: bytes, k: int) -> list[ClusterId]:
    """Efraimidis-Spirakis with weight t_c = sqrt(s_c): top-k by ln(u_c)/t_c, ties by id."""
    if k <= 0:
        return []
    keyed: list[tuple[float, ClusterId]] = []
    for cid, score in scores.items():
        if score <= 0:
            continue
        t_c = math.sqrt(score)
        key = math.log(uniform_from(randomness, cid)) / t_c
        keyed.append((key, cid))
    keyed.sort(key=lambda item: (-item[0], item[1]))
    return [cid for _, cid in keyed[:k]]


def split_prizes(
    pot: int, winners: Sequence[ClusterId], prize_split: Sequence[float]
) -> tuple[dict[ClusterId, int], int]:
    """Rank i gets floor(pot·split[i]); unused ranks and dust stay in the pot (returned)."""
    prizes: dict[ClusterId, int] = {}
    paid = 0
    for share, cid in zip(prize_split, winners, strict=False):
        amount = math.floor(pot * share)
        prizes[cid] = amount
        paid += amount
    return prizes, pot - paid
