"""Run a list of agents over T minutes against a shared pool. Deterministic for a given seed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from engine.types import FirstFunding, PricePoint, SolTransfer, TokenEvent
from sim.agents import Books, Clock
from sim.market import ConstantProductPool

# Default deep pool so small agent trades have little slippage.
DEFAULT_TOKENS = 10**15
DEFAULT_SOL = 10**15  # mid = 1 lamport / base unit


class Agent(Protocol):
    def step(self, ts: int, pool: ConstantProductPool, books: Books, clock: Clock) -> None: ...


@dataclass(frozen=True)
class WorldResult:
    events: list[TokenEvent]
    sol_transfers: list[SolTransfer]
    fundings: list[FirstFunding]
    prices: list[PricePoint]
    pool: ConstantProductPool
    start_ts: int
    t1: int
    seed: int


def run_world(
    seed: int,
    minutes: int,
    agents: list[Agent],
    *,
    start_ts: int = 0,
    token_reserve: int = DEFAULT_TOKENS,
    sol_reserve: int = DEFAULT_SOL,
    fee_bps: int = 30,
) -> WorldResult:
    """Step each minute in [start_ts, start_ts + minutes*60). Event sigs come from PCG64(seed)."""
    if minutes <= 0:
        raise ValueError("minutes must be > 0")
    rng = np.random.Generator(np.random.PCG64(seed))
    clock_seed = int(rng.integers(0, 2**31))
    pool = ConstantProductPool(token_reserve, sol_reserve, fee_bps)
    books = Books()
    clock = Clock(start_ts, seed=clock_seed)
    t1 = start_ts + minutes * 60
    for m in range(minutes):
        ts = start_ts + m * 60
        for agent in agents:
            agent.step(ts, pool, books, clock)
        pool.record_minute(ts)
    return WorldResult(
        books.events, books.sol_transfers, books.fundings, pool.prices, pool, start_ts, t1, seed
    )
