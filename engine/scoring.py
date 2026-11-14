"""Hold multiplier, churn discount, underwater boost, score (COIN_MATH §3-6). Owner: Grok."""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction

from engine.params import ChurnParams, HoldParams, UnderwaterParams
from engine.types import Lot, LotSource

_DAY = 86_400
_EPS = 1.0  # one token base unit, as in ENGINE_DESIGN / the issue spec


def hold_multiplier(age_days: float, p: HoldParams) -> float:
    """h(a) = 1 + min(1, ln(1+a) / ln(1+horizon_days))."""
    age = max(0.0, age_days)
    return 1.0 + min(1.0, math.log(1.0 + age) / math.log(1.0 + p.horizon_days))


def amount_weighted_hold(lots: Sequence[Lot], t: int, p: HoldParams) -> float:
    """H = Σ amount·h(age) / Σ amount, at time t. 1.0 for no lots."""
    total = 0
    weighted = 0.0
    for lot in lots:
        if lot.amount <= 0:
            continue
        age_days = (t - lot.t_acquired) / _DAY
        total += lot.amount
        weighted += lot.amount * hold_multiplier(age_days, p)
    if total == 0:
        return 1.0
    return weighted / total


def churn_factor(v_buy: int, v_sell: int, twab_balance: float, p: ChurnParams) -> float:
    """F = 1 / (1 + κ · min(v_buy, v_sell) / max(twab, ε))."""
    chi = min(v_buy, v_sell) / max(twab_balance, _EPS)
    return 1.0 / (1.0 + p.kappa * chi)


def underwater_boost(lots: Sequence[Lot], twap: float, t: int, p: UnderwaterParams) -> float:
    """U = 1 + β · min(D, D_max) / D_max over POOL_BUY lots aged ≥ min_age_hours."""
    if twap <= 0:
        raise ValueError(f"twap must be > 0, got {twap}")
    min_age = p.min_age_hours * 3600.0
    weighted_d = 0.0
    total = 0
    for lot in lots:
        if lot.source is not LotSource.POOL_BUY or lot.cost_lamports_per_token <= 0:
            continue
        if t - lot.t_acquired < min_age or lot.amount <= 0:
            continue
        drawdown = max(0.0, 1.0 - twap / lot.cost_lamports_per_token)
        weighted_d += lot.amount * drawdown
        total += lot.amount
    if total == 0:
        return 1.0
    d_bar = weighted_d / total
    return 1.0 + p.beta * min(d_bar, p.d_max) / p.d_max


def score(twab_balance: float, hold: float, churn: float, boost: float) -> float:
    """s = B̄ · H · F · U."""
    if twab_balance < 0 or hold < 0 or churn < 0 or boost < 0:
        raise ValueError("score inputs must be >= 0")
    return twab_balance * hold * churn * boost


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §3–4. Defaults match the published knot table / T_START=2h.
# Config/schema adoption is a later issue (gap A). Callers may pass another
# knot table or T_START; this module does not choose kiwi's variants.
# ---------------------------------------------------------------------------

HOUR = 3_600
# _DAY already defined above as 86_400.
DEFAULT_T_START_SECONDS = 2 * HOUR
DEFAULT_BOOST_AGE_SECONDS = 48 * HOUR  # E1/E2 split; §5 boost may start here
DEFAULT_HOLD_KNOTS: tuple[tuple[int, Fraction], ...] = (
    (2 * HOUR, Fraction(1)),
    (6 * HOUR, Fraction(23, 20)),  # 1.15
    (12 * HOUR, Fraction(13, 10)),  # 1.30
    (24 * HOUR, Fraction(3, 2)),  # 1.50
    (48 * HOUR, Fraction(7, 4)),  # 1.75
    (72 * HOUR, Fraction(19, 10)),  # 1.90
    (7 * _DAY, Fraction(21, 10)),  # 2.10
    (14 * _DAY, Fraction(23, 10)),  # 2.30
    (30 * _DAY, Fraction(5, 2)),  # 2.50
    (60 * _DAY, Fraction(27, 10)),  # 2.70
    (90 * _DAY, Fraction(14, 5)),  # 2.80
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
# Default u_lot = 1 (boost off at launch). Keep score() (v0.2 product) unchanged.
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
