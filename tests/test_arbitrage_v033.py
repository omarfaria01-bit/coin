"""#136: the deterministic arbitrage agent and the §14 dump/pump rows."""

from __future__ import annotations

import random
from fractions import Fraction
from pathlib import Path

import pytest

import sim.arbitrage_v033 as arb
import sim.report_v033 as rep
from sim.gap_rows_v033 import ROWS as GAP_ROWS
from sim.market import ConstantProductPool
from sim.run import main

T, S = 10**15, 10**9  # token base units, lamports: mid = 1e-6 lamports per base unit


def _pool() -> ConstantProductPool:
    return ConstantProductPool(T, S)


@pytest.mark.parametrize(("name", "fn"), [(n, f) for n, _, f in arb.ROWS])
def test_arbitrage_rows_pass_on_twenty_seeds(name: str, fn) -> None:
    for seed in range(20):
        out = fn(random.Random(f"{name}:{seed}"))
        assert out.passed, f"{name} seed {seed}: {out.evidence}"


def test_arbitrage_rows_are_registered_and_no_longer_a_gap() -> None:
    assert {name for name, _, _ in arb.ROWS} <= {name for name, _, _ in GAP_ROWS}
    assert not any("Dump / pump" in name for name, _, _ in rep.GAPS)


def test_arbitrage_rows_are_in_the_acceptance_report(tmp_path: Path) -> None:
    report = tmp_path / "acc.md"
    assert main(["--acceptance", "--seeds", "1", "--out", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    for name, cond, _ in arb.ROWS:
        assert f"| {name} | {cond} | PASS |" in text


def test_agent_does_nothing_at_the_reference() -> None:
    pool = _pool()
    agent = arb.ArbitrageAgent(arb.mid_price(pool))
    assert not agent.mispriced(pool)
    assert agent.step(pool) is None


def test_agent_ignores_a_deviation_inside_the_fee_band() -> None:
    pool = _pool()
    agent = arb.ArbitrageAgent(arb.mid_price(pool))
    pool.sell(pool.token_reserve // 10_000)  # ~0.01%: smaller than the 30 bps fee band
    assert not agent.mispriced(pool)
    assert agent.step(pool) is None


def test_agent_buys_a_dumped_pool_back_to_the_reference() -> None:
    pool = _pool()
    reference = arb.mid_price(pool)
    pool.sell(T // 20)
    assert arb.mid_price(pool) < reference
    trade = arb.ArbitrageAgent(reference).step(pool)
    assert trade is not None and trade.side == "buy"
    assert trade.amount_out * reference > trade.amount_in  # the agent's profit
    assert abs(arb.mid_price(pool) / reference - 1) <= Fraction(1, 10_000)


def test_agent_sells_a_pumped_pool_back_to_the_reference() -> None:
    pool = _pool()
    reference = arb.mid_price(pool)
    pool.buy(S // 20)
    assert arb.mid_price(pool) > reference
    trade = arb.ArbitrageAgent(reference).step(pool)
    assert trade is not None and trade.side == "sell"
    assert trade.amount_out > trade.amount_in * reference  # the agent's profit
    assert abs(arb.mid_price(pool) / reference - 1) <= Fraction(1, 10_000)


@pytest.mark.parametrize("kind", ["dump", "pump"])
def test_round_trip_is_deterministic_and_loses_money(kind: str) -> None:
    first = arb.round_trip(kind, T, S, 500, arbs=True)
    again = arb.round_trip(kind, T, S, 500, arbs=True)
    control = arb.round_trip(kind, T, S, 500, arbs=False)
    assert first == again  # frozen dataclass, exact Fractions: same numbers every time
    assert first.arb_trades == 1 and first.arb_profit > 0
    assert abs(first.restored / first.reference - 1) <= Fraction(1, 10_000)
    assert first.pnl < 0 and control.pnl < 0
    assert first.pnl < control.pnl  # arbitrage removes the mispricing, so the attack costs more


def test_bad_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        arb.ArbitrageAgent(Fraction(0))
    with pytest.raises(ValueError):
        arb.round_trip("sideways", T, S, 500, arbs=True)
