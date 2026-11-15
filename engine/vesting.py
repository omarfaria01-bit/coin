"""Price-weighted vesting and soft-mode forfeits (COIN_MATH §11). Owner: Grok."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from engine.params import VestingParams
from engine.types import ClusterId, EventKind, TokenEvent, WalletId

# P̃_h(t) for a minute boundary t, or None if the 24h window has an untrusted second.
PriceAt = Callable[[int], Fraction | None]

_DAY = 86_400


def breaches_soft_lock(balance_after_outflow: int, locked: int) -> bool:
    """Soft mode: any outflow (sell OR transfer) that leaves balance < locked is a breach."""
    return balance_after_outflow < locked


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §11. Linear u_price on the 24h harmonic mean.
# This supersedes D14 (log unlock + arithmetic TWAP) and the 36h follow-up.
# ---------------------------------------------------------------------------

_HOUR = 3_600


def _as_frac(value: int | Fraction) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int | Fraction):
        raise TypeError("value must be an int or Fraction")
    return value if isinstance(value, Fraction) else Fraction(value)


def _clamp_frac(value: Fraction, lo: Fraction, hi: Fraction) -> Fraction:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def harmonic_mean(prices: Sequence[int | Fraction]) -> Fraction:
    """Equal-weight harmonic mean of strictly positive prices."""
    if not prices:
        raise ValueError("prices must be non-empty")
    acc = Fraction(0)
    for raw in prices:
        price = _as_frac(raw)
        if price <= 0:
            raise ValueError("prices must be > 0")
        acc += 1 / price
    return Fraction(len(prices), 1) / acc


def u_price_linear(
    p_harmonic: int | Fraction, p_entry: int | Fraction, m: int | Fraction
) -> Fraction:
    """u_price = clamp((P̃_h / P_entry − 1) / (M − 1), 0, 1). Each +1× unlocks 1/(M−1)."""
    mean = _as_frac(p_harmonic)
    entry = _as_frac(p_entry)
    cap = _as_frac(m)
    if cap <= 1:
        raise ValueError("M must be > 1")
    if entry <= 0 or mean <= 0:
        return Fraction(0)
    ratio = mean / entry
    return _clamp_frac((ratio - 1) / (cap - 1), Fraction(0), Fraction(1))


def unlocked_fraction_v033(
    prev: int | Fraction,
    t: int,
    t0: int,
    p_harmonic: int | Fraction,
    p_entry: int | Fraction,
    p: VestingParams,
    *,
    window_trusted: bool = True,
) -> Fraction:
    """max(prev, u_time, u_price); u_price only if t ≥ t0 + 24h and the window is trusted."""
    prior = _as_frac(prev)
    if prior < 0 or prior > 1:
        prior = _clamp_frac(prior, Fraction(0), Fraction(1))
    horizon = int(Fraction(str(p.t_v_days)) * _DAY)
    if horizon <= 0:
        raise ValueError("t_v_days must be > 0")
    elapsed = t - t0
    u_time = _clamp_frac(
        Fraction(elapsed, horizon) if elapsed > 0 else Fraction(0), Fraction(0), Fraction(1)
    )
    window_s = int(Fraction(str(p.unlock_twap_hours)) * _HOUR)
    u_price = Fraction(0)
    if window_trusted and elapsed >= window_s:
        u_price = u_price_linear(p_harmonic, p_entry, Fraction(str(p.m)))
    return _clamp_frac(max(prior, u_time, u_price), Fraction(0), Fraction(1))


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §11 B (soft mode): forfeit + taint. Minute-boundary unlocks.
# ---------------------------------------------------------------------------

_MINUTE = 60


@dataclass(frozen=True, slots=True)
class VestedLot:
    """One early buy (or the dev buy) under vesting, owned by ``cluster``."""

    cluster: ClusterId
    amount: int
    t0: int  # buy time (unix seconds)
    p_entry: Fraction  # Q base units per token base unit, > 0


@dataclass(frozen=True, slots=True)
class SoftVestingResult:
    forfeit_until: dict[ClusterId, int]  # score 0 (and no draws) while t < value
    taint_until: dict[tuple[str, int], int]  # (sig, ix) → lots moved by it tainted until
    unlocked: tuple[Fraction, ...] = ()  # per vested lot (input order) at ``t_end``, if given


class _Unlock:
    """Monotone ``unlocked`` of one lot, advanced minute by minute (§11)."""

    def __init__(self, lot: VestedLot, p: VestingParams, p_harmonic: PriceAt) -> None:
        self.lot, self.p, self.p_harmonic = lot, p, p_harmonic
        self.value = Fraction(0)
        self.next_minute = -(-lot.t0 // _MINUTE) * _MINUTE  # first boundary ≥ t0

    def at(self, t: int) -> Fraction:
        last = (t // _MINUTE) * _MINUTE
        while self.next_minute <= last and self.value < 1:
            m = self.next_minute
            mean = self.p_harmonic(m)  # None: some second of the 24h window untrusted
            self.value = unlocked_fraction_v033(
                self.value,
                m,
                self.lot.t0,
                mean if mean is not None else 1,
                self.lot.p_entry,
                self.p,
                window_trusted=mean is not None,
            )
            self.next_minute += _MINUTE
        return self.value


def soft_vesting_breaches(
    events: Sequence[TokenEvent],
    vested: Sequence[VestedLot],
    p: VestingParams,
    p_harmonic: PriceAt,
    *,
    cluster_of: Mapping[WalletId, ClusterId] | None = None,
    excluded: frozenset[WalletId] = frozenset(),
    t_end: int | None = None,
) -> SoftVestingResult:
    """Replay the log; flag outflows that leave a cluster below ``locked_c`` (§11 B).

    An outflow is a sell, or a transfer to another cluster (internal moves never
    count). If after it ``balance_c < locked_c(t)``, the cluster is forfeited until
    ``t + forfeit_days`` and, for a transfer, the moved tokens are tainted until the
    same time (the ledger carries the taint, see ``engine.ledger.build_ledger``).
    A sale to the pool ends the tokens' life in the ledger, so it taints nothing.
    """
    clusters = cluster_of or {}
    forfeit_s = int(Fraction(str(p.forfeit_days)) * _DAY)
    unlocks: dict[ClusterId, list[_Unlock]] = {}
    in_order: list[_Unlock] = []
    for lot in vested:
        if lot.amount <= 0 or lot.p_entry <= 0:
            raise ValueError("vested lot needs amount > 0 and p_entry > 0")
        unlock = _Unlock(lot, p, p_harmonic)
        in_order.append(unlock)
        unlocks.setdefault(lot.cluster, []).append(unlock)
    balance: dict[ClusterId, int] = {}
    forfeit: dict[ClusterId, int] = {}
    taint: dict[tuple[str, int], int] = {}

    def cid(w: WalletId | None) -> ClusterId | None:
        return None if w is None or w in excluded else clusters.get(w, w)

    for ev in sorted(events, key=lambda e: (e.slot, e.sig, e.ix)):
        src = cid(ev.src) if ev.kind is not EventKind.BUY else None
        dst = cid(ev.dst) if ev.kind is not EventKind.SELL else None
        if src is not None and src == dst:
            continue  # internal move: the locked amount follows the cluster
        if dst is not None:
            balance[dst] = balance.get(dst, 0) + ev.amount
        if src is None:
            continue
        balance[src] = balance.get(src, 0) - ev.amount
        locked = sum(((1 - u.at(ev.ts)) * u.lot.amount for u in unlocks.get(src, ())), Fraction(0))
        if balance[src] < locked:
            until = ev.ts + forfeit_s
            forfeit[src] = max(forfeit.get(src, 0), until)
            if ev.kind is EventKind.TRANSFER:
                taint[(ev.sig, ev.ix)] = until
    at_end = () if t_end is None else tuple(u.at(t_end) for u in in_order)
    return SoftVestingResult(dict(sorted(forfeit.items())), dict(sorted(taint.items())), at_end)
