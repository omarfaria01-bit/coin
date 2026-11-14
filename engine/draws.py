"""Weighted draw without replacement (COIN_MATH §9). Owner: Grok, from docs/ENGINE_DESIGN.md §5."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
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
        if not math.isfinite(score):
            raise ValueError(f"non-finite score for {cid}")
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
    if pot < 0:
        raise ValueError("pot must be >= 0")
    if any(share < 0 for share in prize_split):
        raise ValueError("prize_split entries must be >= 0")
    if sum(prize_split) > 1 + 1e-9:
        raise ValueError("prize_split must sum to <= 1")
    if len(winners) != len(set(winners)):
        raise ValueError("duplicate winners")
    prizes: dict[ClusterId, int] = {}
    paid = 0
    for share, cid in zip(prize_split, winners, strict=False):
        amount = min(int(Fraction(share) * pot), pot - paid)
        prizes[cid] = amount
        paid += amount
    remainder = pot - paid
    return prizes, remainder


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §9. Integer isqrt weights + rejection sampling.
# Draws are off at launch (§16). Keep draw_winners (E–S) above unchanged.
# ---------------------------------------------------------------------------

DRAW_STREAM_PREFIX = b"COIN_SYSTEM_DRAW_V1"
DRAW_PERIOD_EPOCHS_DEFAULT = 7
DELTA_DEFAULT = Fraction(1)
MIN_DRAW_SHARE_DEFAULT = Fraction(1, 100_000)
DRAWS_ENABLED_DEFAULT = False
TREASURY_ENABLED_DEFAULT = False  # §12 / §16: bot stays off at launch
_TWO256 = 1 << 256
_WEIGHT_DOMAIN = 1 << 128


def isqrt(n: int) -> int:
    """Integer square root (floor), Newton; no floating point."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an int")
    if n < 0:
        raise ValueError("isqrt is not defined for negative numbers")
    if n < 2:
        return n
    x = 1 << ((n.bit_length() + 1) // 2)
    while True:
        y = (x + n // x) // 2
        if y >= x:
            return x
        x = y


def draw_weight(score_sum: int | Fraction) -> int:
    """w_c = isqrt(floor(Σ s_c)). Zero weights must be dropped by the caller."""
    if isinstance(score_sum, bool):
        raise TypeError("score_sum must be an int or Fraction")
    if isinstance(score_sum, Fraction):
        if score_sum < 0:
            raise ValueError("score_sum must be >= 0")
        n = score_sum.numerator // score_sum.denominator
    elif isinstance(score_sum, int):
        if score_sum < 0:
            raise ValueError("score_sum must be >= 0")
        n = score_sum
    else:
        raise TypeError("score_sum must be an int or Fraction")
    return isqrt(n)


def min_eligible_epochs(period_epochs: int = DRAW_PERIOD_EPOCHS_DEFAULT) -> int:
    """⌈5n/7⌉ of the period. Callers may pass n=1 or n=3 without changing the default."""
    if isinstance(period_epochs, bool) or not isinstance(period_epochs, int):
        raise TypeError("period_epochs must be an int")
    if period_epochs <= 0:
        raise ValueError("period_epochs must be > 0")
    return (5 * period_epochs + 6) // 7


def is_draw_eligible(
    reward_eligible_epochs: int,
    period_epochs: int,
    twab_final: int | Fraction,
    total_supply: int,
    *,
    forfeited: bool = False,
    min_draw_share: Fraction = MIN_DRAW_SHARE_DEFAULT,
) -> bool:
    """Price-free draw eligibility (COIN_MATH §9)."""
    if forfeited:
        return False
    if reward_eligible_epochs < min_eligible_epochs(period_epochs):
        return False
    if total_supply < 0:
        raise ValueError("total_supply must be >= 0")
    twab = twab_final if isinstance(twab_final, Fraction) else Fraction(twab_final)
    if twab < 0:
        raise ValueError("twab must be >= 0")
    return twab >= min_draw_share * total_supply


def draw_stream_int(
    genesis_hash: bytes,
    mint: bytes,
    draw_index: int,
    snapshot_hash: bytes,
    rho: bytes,
    i: int,
) -> int:
    """x_i = SHA-256(prefix ‖ genesis ‖ mint ‖ draw_index ‖ snapshot ‖ ρ ‖ i) as a 256-bit int.

    Hashes and ``rho`` and ``mint`` are 32-byte fields; ``draw_index`` and ``i``
    are uint64 big-endian. The field sizes make the concatenation unambiguous.
    """
    for name, val in (
        ("genesis_hash", genesis_hash),
        ("mint", mint),
        ("snapshot_hash", snapshot_hash),
        ("rho", rho),
    ):
        if not isinstance(val, bytes | bytearray) or len(val) != 32:
            raise ValueError(f"{name} must be 32 bytes")
    if draw_index < 0 or i < 0:
        raise ValueError("draw_index and i must be >= 0")
    digest = sha256(
        DRAW_STREAM_PREFIX
        + bytes(genesis_hash)
        + bytes(mint)
        + draw_index.to_bytes(8, "big")
        + bytes(snapshot_hash)
        + bytes(rho)
        + i.to_bytes(8, "big")
    ).digest()
    return int.from_bytes(digest, "big")


def accept_draw_uniform(x: int, weight_sum: int) -> int | None:
    """Return r = x mod W, or None if x is outside the unbiased range."""
    if weight_sum <= 0:
        raise ValueError("weight_sum must be > 0")
    if not (0 <= x < _TWO256):
        raise ValueError("x must be a 256-bit integer")
    limit = (_TWO256 // weight_sum) * weight_sum
    if x >= limit:
        return None
    return x % weight_sum


def sample_draw_winners(
    weights: Mapping[ClusterId, int],
    *,
    genesis_hash: bytes,
    mint: bytes,
    draw_index: int,
    snapshot_hash: bytes,
    rho: bytes,
    k: int,
) -> list[ClusterId]:
    """Sequential weighted sampling without replacement, no modulo bias."""
    if k <= 0:
        return []
    remaining = {cid: w for cid, w in weights.items() if w > 0}
    if not remaining:
        return []
    total = sum(remaining.values())
    if not (1 <= total < _WEIGHT_DOMAIN):
        raise ValueError(f"total weight must satisfy 1 ≤ W < 2^128, got {total}")
    winners: list[ClusterId] = []
    i = 0
    while len(winners) < k and remaining:
        w_sum = sum(remaining.values())
        if w_sum <= 0:
            break
        while True:
            x = draw_stream_int(genesis_hash, mint, draw_index, snapshot_hash, rho, i)
            i += 1
            r = accept_draw_uniform(x, w_sum)
            if r is not None:
                break
        cursor = 0
        chosen: ClusterId | None = None
        for cid in sorted(remaining):
            cursor += remaining[cid]
            if cursor > r:
                chosen = cid
                break
        if chosen is None:
            raise ValueError("draw sampler failed to select a winner")
        winners.append(chosen)
        del remaining[chosen]
    return winners
