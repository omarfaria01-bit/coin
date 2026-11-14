"""Constant-product pool invariants and world determinism."""

from __future__ import annotations

import hashlib
import json

import pytest

from engine.types import TokenEvent
from sim.agents import Flipper, Holder, snapshot_sniper, wallet_id
from sim.market import ConstantProductPool
from sim.world import run_world


def test_k_never_decreases_on_buy_and_sell() -> None:
    pool = ConstantProductPool(10**12, 10**12, fee_bps=30)
    k0 = pool.k
    tokens = pool.buy(10**9)
    assert pool.k >= k0
    k1 = pool.k
    pool.sell(tokens)
    assert pool.k >= k1
    # Zero fee still does not shrink k (floor on output).
    pool = ConstantProductPool(10**9, 10**9, fee_bps=0)
    k0 = pool.k
    t = pool.buy(1_000_000)
    assert pool.k >= k0
    pool.sell(t)
    assert pool.k >= k0


def test_buy_then_sell_loses_at_least_the_fees() -> None:
    pool = ConstantProductPool(10**15, 10**15, fee_bps=30)
    paid = 10**9
    fee = pool.fee_on(paid)
    tokens = pool.buy(paid)
    back = pool.sell(tokens)
    assert back <= paid - fee
    assert back < paid


def test_same_seed_identical_event_list_hash() -> None:
    def dump(seed: int) -> str:
        world = run_world(
            seed,
            60,
            [
                Holder("h", "f", 10**8, buy_ts=0),
                snapshot_sniper("s", "f", 10**8, t1=60 * 60),
                Flipper("fl", "f", 10**8, start_ts=0, t1=60 * 60, per_day=5),
            ],
        )
        payload = [
            (e.slot, e.ts, e.sig, e.ix, e.kind, e.src, e.dst, e.amount, e.lamports, e.fee_payer)
            for e in world.events
        ]
        return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()

    first = dump(7)
    assert dump(7) == first
    assert dump(8) != first


def test_wallet_ids_are_stable_and_buy_emits_token_event() -> None:
    assert wallet_id("holder") == wallet_id("holder")
    assert wallet_id("a") != wallet_id("b")
    world = run_world(1, 10, [Holder("h", "f", 10**8, 0)])
    assert world.events and isinstance(world.events[0], TokenEvent)
    assert world.fundings[0].funder == wallet_id("f")
    with pytest.raises(ValueError, match="reserves"):
        ConstantProductPool(0, 1)
    with pytest.raises(ValueError, match="t1"):
        p = ConstantProductPool(100, 100)
        p.record_minute(0)
        p.twap(5, 5)
