"""Constant-product pool (x·y=k) with integer reserves and a 1-min price series."""

from __future__ import annotations

from engine.types import PricePoint

_BPS = 10_000


class ConstantProductPool:
    """`buy(lamports) -> tokens` and `sell(tokens) -> lamports`; fee stays in the pool."""

    def __init__(self, token_reserve: int, sol_reserve: int, fee_bps: int = 30) -> None:
        if token_reserve <= 0 or sol_reserve <= 0:
            raise ValueError("reserves must be > 0")
        if not 0 <= fee_bps < _BPS:
            raise ValueError(f"fee_bps must be in [0, {_BPS}), got {fee_bps}")
        self.token_reserve = token_reserve
        self.sol_reserve = sol_reserve
        self.fee_bps = fee_bps
        self.prices: list[PricePoint] = []

    @property
    def k(self) -> int:
        return self.token_reserve * self.sol_reserve

    def mid_price(self) -> float:
        """Lamports per token base unit (D13)."""
        return self.sol_reserve / self.token_reserve

    def fee_on(self, amount: int) -> int:
        return amount - amount * (_BPS - self.fee_bps) // _BPS

    def _effective(self, amount: int) -> int:
        return amount * (_BPS - self.fee_bps) // _BPS

    def buy(self, lamports: int) -> int:
        if lamports <= 0:
            raise ValueError("buy amount must be > 0")
        dx = self._effective(lamports)
        if dx <= 0:
            raise ValueError("buy is entirely fee")
        out = (dx * self.token_reserve) // (self.sol_reserve + dx)
        if out <= 0:
            raise ValueError("buy output is 0")
        self.sol_reserve += lamports
        self.token_reserve -= out
        return out

    def sell(self, tokens: int) -> int:
        if tokens <= 0:
            raise ValueError("sell amount must be > 0")
        if tokens >= self.token_reserve:
            raise ValueError("sell drains the pool")
        dy = self._effective(tokens)
        if dy <= 0:
            raise ValueError("sell is entirely fee")
        out = (dy * self.sol_reserve) // (self.token_reserve + dy)
        if out <= 0:
            raise ValueError("sell output is 0")
        self.token_reserve += tokens
        self.sol_reserve -= out
        return out

    def record_minute(self, ts: int) -> None:
        if self.prices and ts < self.prices[-1].ts:
            raise ValueError("price series must be non-decreasing in time")
        if self.prices and ts == self.prices[-1].ts:
            self.prices[-1] = PricePoint(ts, self.mid_price())
            return
        self.prices.append(PricePoint(ts, self.mid_price()))

    def twap(self, t0: int, t1: int) -> float:
        """Time-weighted mid over [t0, t1) from the 1-min series."""
        if t1 <= t0:
            raise ValueError(f"t1 must be > t0, got t0={t0} t1={t1}")
        if not self.prices:
            raise ValueError("no prices recorded")
        price = self.prices[0].price
        cursor = t0
        numer = 0.0
        for pt in self.prices:
            if pt.ts <= t0:
                price = pt.price
                continue
            if pt.ts >= t1:
                break
            if pt.ts > cursor:
                numer += price * (pt.ts - cursor)
                cursor = pt.ts
            price = pt.price
        numer += price * (t1 - cursor)
        return numer / (t1 - t0)
