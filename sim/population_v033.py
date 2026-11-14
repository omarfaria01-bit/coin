"""Multi-epoch population on the real engine (#84 step 3, reused by #85 variants).

Modelled agents, not forecasts: loyal holders, casual holders who leave faster when their
reward per token trails the crowd, reward farmers who sell once the curve flattens, 4h
traders, whales, €100 holders and holding-time probes. Each day is one `run_epoch` over the
whole log so far, with the state carried; payouts are exact ints in lamports.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction

from engine.epoch import EpochResult, empty_state, run_epoch
from engine.params import CoinParams
from engine.scoring import h_of_age
from sim.acceptance_v033 import DAY, HOUR, SUPPLY, TOK, Trades
from sim.agents import wallet_id

INFLOW = 2 * 10**9  # 2 SOL/day of creator fees into the pot (modelled)
EUR_USD, MCAP_USD = Fraction(108, 100), 10**6
SMALL_TOKENS = int(SUPPLY * 100 * EUR_USD / MCAP_USD)  # €100 at a $1M market cap
PROBE_HOURS = (1, 4, 12, 24, 72, 168, 720, 1440, 2160)  # hold length, then sell and re-buy
FARMER_MIN_GAIN = Fraction(105, 100)  # farmer holds while h(a + 30d) / h(a) ≥ this


@dataclass
class Agent:
    wallet: str
    kind: str  # loyal | casual | farmer | trader | whale | small | probe
    tokens: int
    entry: int  # ts of first buy
    hold_s: int = 0  # probes: hold length
    held: int = 0  # current balance
    exit: int | None = None  # ts of the full sale, if any
    held_s: int = 0  # token-seconds actually held (probes)


@dataclass
class Run:
    params: CoinParams
    days: int
    agents: list[Agent]
    results: list[EpochResult] = field(default_factory=list)
    balances: list[dict[str, int]] = field(default_factory=list)  # end-of-day balance

    def paid(self, w: str, d0: int = 0, d1: int | None = None) -> int:
        return sum(r.payouts.get(w, 0) for r in self.results[d0:d1])


def _farmer_exit_day(params: CoinParams) -> int:
    kn, t_start = params.hold.knot_fractions(), params.hold.t_start_seconds
    for mark in (30, 60, 90):
        a = mark * DAY
        if h_of_age(a + 30 * DAY, kn, t_start) < FARMER_MIN_GAIN * h_of_age(a, kn, t_start):
            return mark
    return 10**6


def _crowd(rng: random.Random, n: int) -> list[Agent]:
    out: list[Agent] = []

    def add(kind: str, count: int, size: tuple[int, int], entry_days: int, hold_s: int = 0):
        for i in range(count):
            tokens = rng.randint(*size) * TOK
            entry = rng.randint(0, entry_days * DAY) + HOUR
            out.append(
                Agent(wallet_id(f"pop-{kind}-{i}-{rng.random()}"), kind, tokens, entry, hold_s)
            )

    add("loyal", n // 4, (10**4, 10**6), 10)
    add("casual", n // 2, (10**4, 10**6), 60)
    add("farmer", n // 8, (10**5, 10**6), 10)
    add("trader", max(1, n // 16), (10**5, 10**6), 0)
    add("whale", 2, (2 * 10**7, 5 * 10**7), 3)
    add("small", 3, (SMALL_TOKENS // TOK, SMALL_TOKENS // TOK), 5)
    for h in PROBE_HOURS:
        add("probe", 1, (10**5, 10**5), 0, h * HOUR)
    return out


def simulate(
    seed: int,
    params: CoinParams | None = None,
    days: int = 93,
    n: int = 48,
    inflow: Callable[[int], int] = lambda d: INFLOW,
) -> Run:
    """One seeded population over `days` epochs; same seed → same agents for every variant."""
    params = params or CoinParams()
    rng = random.Random(f"population:{seed}")
    agents, tr = _crowd(rng, n), Trades(f"pop{seed}")
    behave = random.Random(f"behaviour:{seed}")  # draws for leave decisions, variant-independent
    farmer_exit = _farmer_exit_day(params) * DAY
    run, state = Run(params, days, agents), empty_state()
    for d in range(days):
        t0, t1 = d * DAY, (d + 1) * DAY
        rate = _reward_per_token(run, agents, d)
        mean = sum(rate.values()) / len(rate) if rate else 0
        for a in agents:
            _step(a, tr, t0, t1, farmer_exit, rate.get(a.wallet), mean, behave, days * DAY)
        res, state = run_epoch(tr.inputs(t0, inflow(d)), params, state)
        run.results.append(res)
        run.balances.append({a.wallet: a.held for a in agents})
    return run


def _step(a, tr, t0, t1, farmer_exit, rate, mean, behave, end) -> None:
    if a.exit is not None or a.entry >= t1:
        return
    if a.held == 0 and a.kind not in ("trader", "probe"):
        tr.buy(a.wallet, a.tokens, a.entry)
        a.held = a.tokens
    if a.kind == "farmer" and a.entry + farmer_exit < t1:
        _sell_all(a, tr, max(t0, a.entry + farmer_exit))
    elif a.kind == "casual" and a.entry < t0:
        rel = rate / mean if mean and rate is not None else 1
        p = Fraction(15, 1000) * min(
            2, max(Fraction(1, 4), 2 - Fraction(rel).limit_denominator(1000))
        )
        if behave.random() < p:
            _sell_all(a, tr, t0 + behave.randint(0, DAY - 1))
    elif a.kind == "trader":  # 4h in, 4h out
        for k in range(3):
            ts = t0 + k * 8 * HOUR + 60
            tr.buy(a.wallet, a.tokens, ts)
            tr.sell(a.wallet, a.tokens, ts + 4 * HOUR)
    elif a.kind == "probe":
        ts = max(t0, a.entry)
        while ts < t1:
            phase = (ts - a.entry) % (a.hold_s + HOUR)
            if phase == 0:
                tr.buy(a.wallet, a.tokens, ts)
                tr.sell(a.wallet, a.tokens, ts + a.hold_s)
                a.held_s += max(0, min(a.hold_s, end - ts))
                ts += a.hold_s + HOUR
            else:
                ts += a.hold_s + HOUR - phase


def _sell_all(a: Agent, tr: Trades, ts: int) -> None:
    tr.sell(a.wallet, a.held, ts)
    a.held, a.exit = 0, ts


def _reward_per_token(run: Run, agents: list[Agent], d: int) -> dict[str, Fraction]:
    out = {}
    for a in agents:
        if a.kind == "casual" and a.held and d >= 7:
            out[a.wallet] = Fraction(run.paid(a.wallet, d - 7, d), a.held)
    return out
