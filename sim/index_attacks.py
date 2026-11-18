"""#189: offline cost and bound models for the four index attack classes (no I/O, no clock).

Used by ``tests/test_index_hourly_attacks_d39.py`` and
``reports/index_redteam_hourly_d39_2026-11.md``.
Reuses ``index/`` filters and ``engine/hourly_draw.py``; the only new math is the cost of passing
the filters and a constant-product sandwich bound (integers, floor). Analysis only: nothing here
trades, signs or talks to a chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from index.params import IndexParams
from index.select import frac


def min_liquidity_usd(mc_usd: float, p: IndexParams) -> float:
    """Cheapest pool that passes F2 and F11 for a target market cap (the cheap top-10 cost)."""
    f = p.filters
    return max(float(frac(f.min_liquidity_usd)), mc_usd / float(frac(f.max_mc_liquidity_ratio)))


def max_mc_for_liquidity(liquidity_usd: float, p: IndexParams) -> float:
    """Largest market cap F11 lets a pool of this depth carry."""
    return liquidity_usd * float(frac(p.filters.max_mc_liquidity_ratio))


def min_fee_burn_sol(p: IndexParams) -> Fraction:
    """F4 needs `min_total_fees_sol` of DexScreener 24h fees; wash trading pays fee_rate on volume.

    Returns the wash volume (SOL) that produces those fees: fees / dex_fee_rate. The fees come back
    to the pool's LPs (the attacker if they are the LP), so this is turnover, not a sunk cost.
    """
    return frac(p.filters.min_total_fees_sol) / frac(p.filters.dex_fee_rate)


def sybil_wallet_cost_sol(p: IndexParams, per_wallet_sol: Fraction) -> Fraction:
    """Funding needed to show `min_unique_traders` window wallets (F9 counts any size, D38)."""
    return int(frac(p.filters.min_unique_traders)) * per_wallet_sol


@dataclass(frozen=True)
class Sandwich:
    front_in: int  # attacker buy (lamports)
    victim_out: int  # tokens the victim receives
    victim_min_out: int
    profit: int  # attacker lamports after the round trip (can be <= 0)


def _swap_in(x: int, rx: int, ry: int, fee_bps: int) -> int:
    """Constant product with input fee, floor: tokens out for `x` in."""
    xf = x * (10_000 - fee_bps)
    return xf * ry // (rx * 10_000 + xf)


def best_sandwich(
    victim_in: int, r_sol: int, r_tok: int, slippage_bps: int = 300, fee_bps: int = 25
) -> Sandwich:
    """Best front-run that still lets the victim's buy clear with `min_out = quote*(1-slip)`.

    Victim out falls as the attacker's front buy grows, so the largest allowed front is found by
    bisection; profit is then the attacker's round-trip result at that size (and 0 if negative).
    """
    quote = _swap_in(victim_in, r_sol, r_tok, fee_bps)
    min_out = quote * (10_000 - slippage_bps) // 10_000

    def run(a: int) -> Sandwich:
        got = _swap_in(a, r_sol, r_tok, fee_bps)
        s1, t1 = r_sol + a, r_tok - got
        v_out = _swap_in(victim_in, s1, t1, fee_bps)
        s2, t2 = s1 + victim_in, t1 - v_out
        # attacker sells `got` tokens back (token -> SOL, same fee on the token side)
        back = _swap_in(got, t2, s2, fee_bps)
        return Sandwich(a, v_out, min_out, back - a)

    lo, hi = 0, 10 * r_sol
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if run(mid).victim_out >= min_out:
            lo = mid
        else:
            hi = mid - 1
    return run(lo)
