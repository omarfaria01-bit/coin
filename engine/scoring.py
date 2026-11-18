"""Hold multiplier, churn discount, underwater boost, score (COIN_MATH §3-6). Owner: Grok."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from engine.types import Lot, LotSource

_DAY = 86_400

# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §3–4. Defaults match the published knot table / T_START=6h (D21).
# Config/schema adoption is a later issue (gap A). Callers may pass another
# knot table or T_START; this module does not choose kiwi's variants.
# ---------------------------------------------------------------------------

HOUR = 3_600
# _DAY already defined above as 86_400.
DEFAULT_T_START_SECONDS = 1 * HOUR  # D27 (kiwi 18 Nov): was 6h (D21)
DEFAULT_BOOST_AGE_SECONDS = 48 * HOUR  # E1/E2 split; §5 boost may start here
DEFAULT_HOLD_KNOTS: tuple[tuple[int, Fraction], ...] = (
    (1 * HOUR, Fraction(1)),
    (90 * 60, Fraction(1)),  # 1h-1h30: 1x
    (105 * 60, Fraction(3, 2)),  # 1h45: 1.5x
    (2 * HOUR, Fraction(2)),
    (150 * 60, Fraction(3)),
    (3 * HOUR, Fraction(4)),
    (4 * HOUR, Fraction(5)),  # max, flat after (D27)
)


def _validated_knots(
    knots: Sequence[tuple[int, Fraction]] | None,
    t_start: int,
) -> tuple[tuple[int, Fraction], ...]:
    if t_start < 0:
        raise ValueError(f"t_start must be >= 0, got {t_start}")
    raw = DEFAULT_HOLD_KNOTS if knots is None else knots
    if not raw:
        raise ValueError("knots must be non-empty")
    out: list[tuple[int, Fraction]] = []
    prev_a = -1
    prev_h = Fraction(-1)
    for age, height in raw:
        a = int(age)
        h = height if isinstance(height, Fraction) else Fraction(height)
        if a < 0 or h < 0:
            raise ValueError("knot age and h must be >= 0")
        if a <= prev_a:
            raise ValueError("knots must be strictly increasing in age")
        if h < prev_h:
            raise ValueError("knots must be nondecreasing in h")
        out.append((a, h))
        prev_a, prev_h = a, h
    # Knots may precede T_START so a later start (6h/12h/48h) can reuse the
    # published table; h(a) is still 0 below T_START.
    return tuple(out)


def h_of_age(
    age_seconds: int,
    knots: Sequence[tuple[int, Fraction]] | None = None,
    t_start_seconds: int | None = None,
) -> Fraction:
    """h(a): 0 below T_START, piecewise linear between knots, flat after 90d."""
    if isinstance(age_seconds, bool) or not isinstance(age_seconds, int):
        raise TypeError("age_seconds must be an int")
    t_start = DEFAULT_T_START_SECONDS if t_start_seconds is None else int(t_start_seconds)
    ks = _validated_knots(knots, t_start)
    if age_seconds < t_start:
        return Fraction(0)
    if age_seconds >= ks[-1][0]:
        return ks[-1][1]
    if age_seconds < ks[0][0]:
        # Custom curve with a gap after T_START: jump to the first-knot height.
        return ks[0][1]
    for i in range(len(ks) - 1):
        a0, h0 = ks[i]
        a1, h1 = ks[i + 1]
        if a0 <= age_seconds <= a1:
            if a1 == a0:
                return h0
            return h0 + (h1 - h0) * Fraction(age_seconds - a0, a1 - a0)
    return ks[-1][1]


def _sum_linear(lo: int, hi: int, a0: int, a1: int, h0: Fraction, h1: Fraction) -> Fraction:
    """Sum of a linear h on [a0, a1] over integer ages k in [lo, hi)."""
    if hi <= lo:
        return Fraction(0)
    n = hi - lo
    if a1 == a0:
        return n * h0
    slope = (h1 - h0) / Fraction(a1 - a0)
    offset_sum = n * (lo - a0) + Fraction(n * (n - 1), 2)
    return n * h0 + slope * offset_sum


def sum_h_of_age(
    age_lo: int,
    age_hi: int,
    knots: Sequence[tuple[int, Fraction]] | None = None,
    t_start_seconds: int | None = None,
) -> Fraction:
    """Σ_{a = age_lo}^{age_hi - 1} h(a) over integer seconds (closed form)."""
    t_start = DEFAULT_T_START_SECONDS if t_start_seconds is None else int(t_start_seconds)
    ks = _validated_knots(knots, t_start)
    lo = max(age_lo, t_start)
    hi = age_hi
    if hi <= lo:
        return Fraction(0)
    total = Fraction(0)
    first_a, first_h = ks[0]
    gap_hi = min(hi, first_a)
    if gap_hi > lo:
        total += (gap_hi - lo) * first_h
    for i in range(len(ks) - 1):
        a0, h0 = ks[i]
        a1, h1 = ks[i + 1]
        total += _sum_linear(max(lo, a0), min(hi, a1), a0, a1, h0, h1)
    last_a, last_h = ks[-1]
    const_lo = max(lo, last_a)
    if hi > const_lo:
        total += (hi - const_lo) * last_h
    return total


def lot_epoch_parts(
    amount: int,
    t_acquired: int,
    t0: int,
    t1: int,
    *,
    tainted_until: int = 0,
    knots: Sequence[tuple[int, Fraction]] | None = None,
    t_start_seconds: int | None = None,
    boost_age_seconds: int = DEFAULT_BOOST_AGE_SECONDS,
) -> tuple[Fraction, Fraction]:
    """``(E1_lot, E2_lot)`` for one lot over the half-open epoch ``[t0, t1)``.

    E1 covers seconds with ``T_START ≤ age < boost_age`` (default 48h);
    E2 covers ``age ≥ boost_age``. Seconds with ``t < tainted_until`` are
    excluded. Each part is ``(amount / E) · Σ h(a(t))`` as an exact Fraction.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("amount must be an int")
    if amount < 0:
        raise ValueError(f"amount must be >= 0, got {amount}")
    if t1 < t0:
        raise ValueError("t1 must be >= t0")
    if boost_age_seconds < 0:
        raise ValueError("boost_age_seconds must be >= 0")
    epoch_len = t1 - t0
    if epoch_len == 0 or amount == 0:
        return Fraction(0), Fraction(0)
    t_start = DEFAULT_T_START_SECONDS if t_start_seconds is None else int(t_start_seconds)
    start_t = max(t0, t_acquired, tainted_until)
    if start_t >= t1:
        return Fraction(0), Fraction(0)

    def part(t_lo: int, t_hi: int) -> Fraction:
        if t_hi <= t_lo:
            return Fraction(0)
        return Fraction(amount, epoch_len) * sum_h_of_age(
            t_lo - t_acquired, t_hi - t_acquired, knots, t_start
        )

    e1_lo = max(start_t, t_acquired + t_start)
    e1_hi = min(t1, t_acquired + boost_age_seconds)
    e2_lo = max(start_t, t_acquired + boost_age_seconds)
    return part(e1_lo, e1_hi), part(e2_lo, t1)


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §6. s = Σ_lots (E1_lot + u_lot · E2_lot). No cluster factor.
# Default u_lot = 1 (boost off at launch).
# ---------------------------------------------------------------------------


def _as_frac(value: int | Fraction) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int | Fraction):
        raise TypeError("value must be an int or Fraction")
    return value if isinstance(value, Fraction) else Fraction(value)


def lot_score(e1: int | Fraction, e2: int | Fraction, u_lot: int | Fraction = 1) -> Fraction:
    """E1_lot + u_lot · E2_lot. ``u_lot`` applies only to the 48h+ part."""
    boost = _as_frac(u_lot)
    if boost < 0:
        raise ValueError(f"u_lot must be >= 0, got {boost}")
    return _as_frac(e1) + boost * _as_frac(e2)


def score_lot(
    amount: int,
    t_acquired: int,
    t0: int,
    t1: int,
    *,
    u_lot: int | Fraction = 1,
    tainted_until: int = 0,
    knots: Sequence[tuple[int, Fraction]] | None = None,
    t_start_seconds: int | None = None,
    boost_age_seconds: int = DEFAULT_BOOST_AGE_SECONDS,
) -> Fraction:
    """One lot's contribution: E1 + u·E2 over the epoch ``[t0, t1)``."""
    e1, e2 = lot_epoch_parts(
        amount,
        t_acquired,
        t0,
        t1,
        tainted_until=tainted_until,
        knots=knots,
        t_start_seconds=t_start_seconds,
        boost_age_seconds=boost_age_seconds,
    )
    return lot_score(e1, e2, u_lot)


def score_lots(
    lots: Sequence[Lot],
    t0: int,
    t1: int,
    *,
    u_lots: Sequence[int | Fraction] | None = None,
    tainted_until: Sequence[int] | None = None,
    knots: Sequence[tuple[int, Fraction]] | None = None,
    t_start_seconds: int | None = None,
    boost_age_seconds: int = DEFAULT_BOOST_AGE_SECONDS,
) -> Fraction:
    """Cluster (or wallet) score: Σ (E1_lot + u_lot · E2_lot).

    No cluster-level factor. Default ``u_lot`` is 1 (boost off at launch).
    Transfer lots always use ``u_lot = 1``, even if a boost is passed.
    An empty list or every lot younger than ``T_START`` returns 0; no division.
    """
    if u_lots is not None and len(u_lots) != len(lots):
        raise ValueError("u_lots must match lots")
    if tainted_until is not None and len(tainted_until) != len(lots):
        raise ValueError("tainted_until must match lots")
    total = Fraction(0)
    for i, lot in enumerate(lots):
        u: int | Fraction = 1 if u_lots is None else u_lots[i]
        if lot.source is LotSource.TRANSFER_IN:
            u = 1
        taint = 0 if tainted_until is None else tainted_until[i]
        total += score_lot(
            lot.amount,
            lot.t_acquired,
            t0,
            t1,
            u_lot=u,
            tainted_until=taint,
            knots=knots,
            t_start_seconds=t_start_seconds,
            boost_age_seconds=boost_age_seconds,
        )
    return total
