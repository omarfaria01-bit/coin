"""Pool price step function, time-weighted means, trusted seconds (COIN_MATH §0).

Exact Fraction/int arithmetic only: no `math` import, no float literals (payout path,
COIN_MATH §0). Price comes from pool reserves, never from swap prints.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

_TRUST_IMPACT = Fraction(1, 20)  # "less than 5%" (COIN_MATH §0 "Trusted second")


@dataclass(frozen=True, slots=True)
class ReservePoint:
    """Pool reserves effective at the end of second `ts` (COIN_MATH §0 "Price").

    `ts` is a clamped block-time second (`engine.events.clamp_block_times`). `reserve_quote`
    and `reserve_base` are the pool's integer reserves (or virtual reserves pre-graduation)
    after all events with block time <= ts, including whatever fees those trades left behind.
    """

    ts: int
    reserve_quote: int
    reserve_base: int

    def __post_init__(self) -> None:
        if self.reserve_quote <= 0 or self.reserve_base <= 0:
            raise ValueError("reserves must be positive")

    @property
    def price(self) -> Fraction:
        return Fraction(self.reserve_quote, self.reserve_base)


def _sorted_points(points: Sequence[ReservePoint]) -> list[ReservePoint]:
    if not points:
        raise ValueError("at least one reserve point is required")
    ordered = sorted(points, key=lambda point: point.ts)
    for a, b in zip(ordered, ordered[1:], strict=False):
        if a.ts == b.ts:
            raise ValueError(f"duplicate reserve point at ts={a.ts}")
    return ordered


def _point_at(ordered: Sequence[ReservePoint], t: int) -> ReservePoint:
    if t < ordered[0].ts:
        raise ValueError(f"no reserve point known before t={t}")
    current = ordered[0]
    for point in ordered:
        if point.ts > t:
            break
        current = point
    return current


def price_at(points: Sequence[ReservePoint], t: int) -> Fraction:
    """p(t) (COIN_MATH §0 "Price"): the price implied by reserves at the end of second t."""
    return _point_at(_sorted_points(points), t).price


def _segments(
    points: Sequence[ReservePoint], t_start: int, t_end: int
) -> Iterator[tuple[int, int, ReservePoint]]:
    """Yield `(seg_start, seg_end, point)` covering `[t_start, t_end)`; one reserve state
    (`point`) is active throughout each segment. One linear pass after a bisect."""
    if t_end <= t_start:
        raise ValueError("window must be non-empty: t_end > t_start")
    ordered = _sorted_points(points)
    if t_start < ordered[0].ts:
        raise ValueError(f"no reserve point known before t_start={t_start}")
    i = bisect_right([p.ts for p in ordered], t_start) - 1  # state active at t_start
    seg_start = t_start
    while seg_start < t_end:
        nxt = ordered[i + 1].ts if i + 1 < len(ordered) else t_end
        seg_end = min(nxt, t_end)
        yield seg_start, seg_end, ordered[i]
        seg_start, i = seg_end, i + 1


def arithmetic_mean(points: Sequence[ReservePoint], t_start: int, t_end: int) -> Fraction:
    """P̄_e (COIN_MATH §0): arithmetic mean of p(t) over the half-open window [t_start, t_end)."""
    total = Fraction(0)
    for seg_start, seg_end, point in _segments(points, t_start, t_end):
        total += point.price * (seg_end - seg_start)
    return total / (t_end - t_start)


def harmonic_mean(points: Sequence[ReservePoint], t_start: int, t_end: int) -> Fraction:
    """P̃_h (COIN_MATH §0): harmonic mean of p over [t_start, t_end) = window / Σ(1/p).

    For the epoch mean P̄_e, call `arithmetic_mean(points, t_e, t_e + 86_400)`; for the
    vesting mean P̃_h(t), call `harmonic_mean(points, t - 86_400, t)`.
    """
    recip_total = Fraction(0)
    for seg_start, seg_end, point in _segments(points, t_start, t_end):
        recip_total += Fraction(seg_end - seg_start) / point.price
    return Fraction(t_end - t_start) / recip_total


class PoolMath(Protocol):
    """A pluggable pool-math callable (COIN_MATH §0 "Trusted second"): the price after a
    simulated swap of `delta_quote` (signed, quote-asset base units) into (positive) or out
    of (negative) the pool, given its current reserves."""

    def __call__(self, reserve_quote: int, reserve_base: int, delta_quote: int) -> Fraction: ...


def constant_product_price_after(
    reserve_quote: int, reserve_base: int, delta_quote: int
) -> Fraction:
    """Price after a simulated constant-product swap of `delta_quote` (signed) into the pool.

    With `p = y/x` and invariant `k = x·y`, adding `delta_quote` to the quote reserve `y`
    gives `y' = y + delta_quote`, `x' = k/y'`, so `p' = y'/x' = (y + delta_quote)^2 / k`.
    """
    if reserve_quote <= 0 or reserve_base <= 0:
        raise ValueError("reserves must be positive")
    new_quote = reserve_quote + delta_quote
    if new_quote <= 0:
        raise ValueError("simulated swap drains the pool")
    k = reserve_quote * reserve_base
    return Fraction(new_quote * new_quote, k)


def is_trusted_second(
    reserve_quote: int,
    reserve_base: int,
    d_trust: int,
    pool_math: PoolMath = constant_product_price_after,
) -> bool:
    """COIN_MATH §0 "Trusted second": true iff a simulated `d_trust` swap, in either
    direction, moves the price by less than 5%. `d_trust` is the caller's `D_TRUST`
    parameter (COIN_MATH default: 2 SOL), in quote-asset base units."""
    if d_trust <= 0:
        raise ValueError("d_trust must be positive")
    old_price = Fraction(reserve_quote, reserve_base)
    for delta in (d_trust, -d_trust):
        new_price = pool_math(reserve_quote, reserve_base, delta)
        if abs(new_price / old_price - 1) >= _TRUST_IMPACT:
            return False
    return True


def untrusted_fraction(
    points: Sequence[ReservePoint],
    t_start: int,
    t_end: int,
    d_trust: int,
    pool_math: PoolMath = constant_product_price_after,
) -> Fraction:
    """Fraction of seconds in [t_start, t_end) that are not a trusted second (COIN_MATH §0,
    §5 "untrusted fraction of an epoch")."""
    untrusted = 0
    for seg_start, seg_end, point in _segments(points, t_start, t_end):
        if not is_trusted_second(point.reserve_quote, point.reserve_base, d_trust, pool_math):
            untrusted += seg_end - seg_start
    return Fraction(untrusted, t_end - t_start)


class HarmonicOracle:
    """P̃_h(t) over the `window` seconds before t, or None when it must not be used (§0, §11).

    None when the window starts before the first reserve point or holds any untrusted
    second ("u_price ... only if every second of the 24h window is trusted"). Points are
    sorted once and Σ dt/p and untrusted seconds are kept as prefix sums, so each query is
    two bisects instead of a pass over the history (vesting asks once per minute per lot).
    """

    def __init__(
        self,
        points: Sequence[ReservePoint],
        window: int,
        d_trust: int,
        pool_math: PoolMath = constant_product_price_after,
    ) -> None:
        if window <= 0:
            raise ValueError("window must be > 0")
        self._window = window
        self._pts = _sorted_points(points) if points else []
        self._ts = [p.ts for p in self._pts]
        self._recip = [Fraction(0)]  # Σ over whole segments [ts_i, ts_{i+1}) of dt/p_i
        self._bad = [0]  # untrusted seconds over the same segments
        self._trusted = [
            is_trusted_second(p.reserve_quote, p.reserve_base, d_trust, pool_math)
            for p in self._pts
        ]
        for i, (a, b) in enumerate(zip(self._pts, self._pts[1:], strict=False)):
            dt = b.ts - a.ts
            self._recip.append(self._recip[-1] + Fraction(dt) / a.price)
            self._bad.append(self._bad[-1] + (0 if self._trusted[i] else dt))

    def _prefix(self, t: int) -> tuple[Fraction, int]:
        """(Σ dt/p, untrusted seconds) over [ts_0, t)."""
        i = bisect_right(self._ts, t - 1) - 1  # state active in second t - 1
        tail = t - self._ts[i]
        point = self._pts[i]
        return (
            self._recip[i] + Fraction(tail) / point.price,
            self._bad[i] + (0 if self._trusted[i] else tail),
        )

    def __call__(self, t: int) -> Fraction | None:
        start = t - self._window
        if not self._pts or start < self._ts[0]:
            return None
        recip_end, bad_end = self._prefix(t)
        recip_start, bad_start = self._prefix(start) if start > self._ts[0] else (Fraction(0), 0)
        if bad_end - bad_start:
            return None
        return Fraction(self._window) / (recip_end - recip_start)
