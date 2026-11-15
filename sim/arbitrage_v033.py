"""Minimal deterministic arbitrage agent on `sim.market`, for the §14 dump/pump rows (#136).

COIN_MATH §14 asks that a dump followed by 6h of no trades, and a pump followed by 24h
of no trades, leave the attacker with a **negative net PnL** when arbitrage agents are
present. Here the agents have one fixed external reference price (the pool mid before
the attack) and trade the constant-product pool whenever its mid leaves the fee band
around that price, walking it back with the smallest integer trade. There is no clock and
no I/O, and every price comparison is an exact `Fraction`, so a row is a pure function of
its seed.

The attacker round-trips the same bag (dump: sell then buy back; pump: buy then sell),
which is the only way to turn a temporary mispricing into cash. The agent's profit is the
attacker's loss, and it is reported next to the PnL.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction

from sim.acceptance_v033 import Outcome
from sim.market import ConstantProductPool

_BPS = 10_000
MINUTES_PER_HOUR = 60


def mid_price(pool: ConstantProductPool) -> Fraction:
    """Pool mid in lamports per token base unit, exactly (D13)."""
    return Fraction(pool.sol_reserve, pool.token_reserve)


def _tokens_for_buy(pool: ConstantProductPool, lamports: int) -> int:
    """`pool.buy` output without mutating the pool."""
    effective = lamports * (_BPS - pool.fee_bps) // _BPS
    if effective <= 0:
        return 0
    return effective * pool.token_reserve // (pool.sol_reserve + effective)


def _lamports_for_sell(pool: ConstantProductPool, tokens: int) -> int:
    """`pool.sell` output without mutating the pool."""
    effective = tokens * (_BPS - pool.fee_bps) // _BPS
    if effective <= 0:
        return 0
    return effective * pool.sol_reserve // (pool.token_reserve + effective)


def _price_after_buy(pool: ConstantProductPool, lamports: int) -> Fraction:
    out = _tokens_for_buy(pool, lamports)
    return Fraction(pool.sol_reserve + lamports, pool.token_reserve - out)


def _price_after_sell(pool: ConstantProductPool, tokens: int) -> Fraction:
    out = _lamports_for_sell(pool, tokens)
    return Fraction(pool.sol_reserve - out, pool.token_reserve + tokens)


def _buy_to(pool: ConstantProductPool, target: Fraction) -> int:
    """Lamports whose post-trade mid is closest to `target` (target above the current mid).

    Buying is monotone: the price after the buy only rises, so a binary search over the
    integers finds the two amounts that straddle the target.
    """
    lo, hi = 1, max(1, pool.sol_reserve)
    while _price_after_buy(pool, hi) < target:
        hi *= 2
    while lo < hi:
        middle = (lo + hi) // 2
        if _price_after_buy(pool, middle) < target:
            lo = middle + 1
        else:
            hi = middle
    if lo == 1:
        return 1
    below, above = _price_after_buy(pool, lo - 1), _price_after_buy(pool, lo)
    return lo - 1 if abs(below - target) < abs(above - target) else lo


def _sell_to(pool: ConstantProductPool, target: Fraction) -> int:
    """Tokens whose post-trade mid is closest to `target` (target below the current mid)."""
    lo, hi = 1, pool.token_reserve - 1
    while lo < hi:
        middle = (lo + hi) // 2
        if _price_after_sell(pool, middle) > target:
            lo = middle + 1
        else:
            hi = middle
    if lo == 1:
        return 1
    below, above = _price_after_sell(pool, lo - 1), _price_after_sell(pool, lo)
    return lo - 1 if abs(below - target) < abs(above - target) else lo


@dataclass(frozen=True)
class ArbTrade:
    side: str  # "buy" | "sell"
    amount_in: int
    amount_out: int


class ArbitrageAgent:
    """One reference price, one pool: trade it back to the reference when it is mispriced."""

    def __init__(self, reference: Fraction) -> None:
        if reference <= 0:
            raise ValueError("reference price must be > 0")
        self.reference = reference

    def band(self, pool: ConstantProductPool) -> tuple[Fraction, Fraction]:
        """No-trade band: inside it a round trip cannot beat the pool fee."""
        fee = Fraction(pool.fee_bps, _BPS)
        return self.reference * (1 - fee), self.reference / (1 - fee)

    def mispriced(self, pool: ConstantProductPool) -> bool:
        low, high = self.band(pool)
        return not low <= mid_price(pool) <= high

    def step(self, pool: ConstantProductPool) -> ArbTrade | None:
        """One trade toward the reference, or None when the pool is inside the band."""
        low, high = self.band(pool)
        price = mid_price(pool)
        if price < low:
            amount = _buy_to(pool, self.reference)
            if amount <= 0 or _tokens_for_buy(pool, amount) <= 0:
                return None
            return ArbTrade("buy", amount, pool.buy(amount))
        if price > high:
            amount = _sell_to(pool, self.reference)
            if amount <= 0 or _lamports_for_sell(pool, amount) <= 0:
                return None
            return ArbTrade("sell", amount, pool.sell(amount))
        return None


@dataclass(frozen=True)
class RoundTrip:
    pnl: Fraction  # attacker's net PnL in lamports
    notional: Fraction  # the capital the attacker put at risk
    restored: Fraction  # pool mid after the no-trade window, before the attacker's exit
    reference: Fraction
    arb_trades: int
    arb_profit: Fraction  # agents' PnL in lamports, the mirror of the attacker's loss


def _window(pool: ConstantProductPool, reference: Fraction, minutes: int) -> tuple[int, Fraction]:
    """No organic trades for `minutes`: only the arbitrage agent acts."""
    agent, trades, profit = ArbitrageAgent(reference), 0, Fraction(0)
    for minute in range(1, minutes + 1):
        trade = agent.step(pool)
        if trade is not None:
            trades += 1
            if trade.side == "buy":
                profit += trade.amount_out * reference - trade.amount_in
            else:
                profit += trade.amount_out - trade.amount_in * reference
        pool.record_minute(minute)  # the 1-min reserve log the §14 row talks about
    return trades, profit


def round_trip(
    kind: str, token_reserve: int, sol_reserve: int, size_bps: int, *, arbs: bool
) -> RoundTrip:
    """Attack, no-trade window, exit. `kind` is "dump" or "pump"; `arbs=False` is the control."""
    if kind not in {"dump", "pump"}:
        raise ValueError(f"kind must be 'dump' or 'pump', got {kind!r}")
    pool = ConstantProductPool(token_reserve, sol_reserve)
    reference = mid_price(pool)
    minutes = (6 if kind == "dump" else 24) * MINUTES_PER_HOUR
    if kind == "dump":
        bag = token_reserve * size_bps // _BPS
        notional = bag * reference
        proceeds = pool.sell(bag)  # push the mid down
        pool.record_minute(0)
        trades, profit = _window(pool, reference, minutes) if arbs else (0, Fraction(0))
        restored = mid_price(pool)
        back = pool.buy(proceeds)  # buy the bag back at the (restored) price
        pnl = back * reference - notional
    else:
        spend = sol_reserve * size_bps // _BPS
        notional = Fraction(spend)
        bag = pool.buy(spend)  # push the mid up
        pool.record_minute(0)
        trades, profit = _window(pool, reference, minutes) if arbs else (0, Fraction(0))
        restored = mid_price(pool)
        proceeds = pool.sell(bag)  # sell the bag at the (restored) price
        pnl = Fraction(proceeds) - notional
    return RoundTrip(pnl, notional, restored, reference, trades, profit)


def _row(kind: str, rng: random.Random) -> Outcome:
    token_reserve = rng.randint(10**14, 10**15)
    sol_reserve = rng.randint(10**8, 10**9)
    size_bps = rng.randint(100, 1_000)  # 1–10% of the pool
    got = round_trip(kind, token_reserve, sol_reserve, size_bps, arbs=True)
    control = round_trip(kind, token_reserve, sol_reserve, size_bps, arbs=False)
    restored = abs(got.restored - got.reference) <= got.reference / _BPS
    ok = got.pnl < 0 and got.arb_trades >= 1 and got.arb_profit > 0 and restored
    hours = 6 if kind == "dump" else 24
    ratio = float(got.restored / got.reference)
    control_ratio = float(control.pnl / control.notional)
    return Outcome(
        ok,
        f"pnl={float(got.pnl):.0f} ({float(got.pnl / got.notional):+.2%} of notional) "
        f"in {hours}h; mid/ref={ratio:.4f}; arbs={got.arb_trades} "
        f"profit={float(got.arb_profit):.0f}; no-arb pnl={control_ratio:+.2%}",
    )


def row_dump_no_trades(rng: random.Random) -> Outcome:
    """Dump, then 6h with no trades (arbitrage agents present): attacker's net PnL < 0."""
    return _row("dump", rng)


def row_pump_no_trades(rng: random.Random) -> Outcome:
    """Pump, then 24h with no trades (arbitrage agents present): attacker's net PnL < 0."""
    return _row("pump", rng)


ROWS = (
    (
        "Dump, then 6h with no trades (arbitrage agents present)",
        "attacker's net PnL < 0; pool mid restored to the reference",
        row_dump_no_trades,
    ),
    (
        "Pump, then 24h with no trades (arbitrage agents present)",
        "attacker's net PnL < 0; pool mid restored to the reference",
        row_pump_no_trades,
    ),
)  # fmt: skip
