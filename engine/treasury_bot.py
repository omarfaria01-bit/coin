"""Anticyclical treasury bot strategy, pure function (COIN_MATH §12). Owner: Claude."""

from __future__ import annotations

from dataclasses import dataclass

from engine.params import TreasuryBotParams


@dataclass(frozen=True, slots=True)
class BotState:
    ts: int
    sol_lamports: int
    tokens: int
    ema_x: float | None
    ewma_var: float | None
    high_water_mark_lamports: int
    day_pnl_lamports: int


@dataclass(frozen=True, slots=True)
class MarketView:
    ts: int
    twap_1m: float
    high_7d: float
    pool_liquidity_lamports: int
    pool_volume_1h_lamports: int
    launch_ts: int
    in_quiet_window: bool  # ±quiet_minutes around a published buyback or payout


@dataclass(frozen=True, slots=True)
class Order:
    side: str  # "buy" | "sell"
    lamports: int


def decide(
    state: BotState, market: MarketView, p: TreasuryBotParams
) -> tuple[BotState, list[Order]]:
    """Update EMA/EWMA, apply breakers, return the new state and at most one order."""
    raise NotImplementedError
