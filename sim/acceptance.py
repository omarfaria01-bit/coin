"""COIN_MATH §14 acceptance scenarios that are not already on main (and not on unmerged #33).

Reuse sim.market / sim.agents / sim.world. Do not touch sim/run.py.
Fee routing is a stub on main, so the decay row uses epoch_budget after a measured volume drop.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.draws import draw_winners
from engine.ledger import build_lots
from engine.merkle import claims_document
from engine.params import (
    ChurnParams,
    HoldParams,
    RewardParams,
    ScoringParams,
    SybilParams,
    UnderwaterParams,
)
from engine.rewards import allocate, capped_shares, epoch_budget
from engine.scoring import amount_weighted_hold, churn_factor, score, underwater_boost
from engine.sybil import build_evidence, cluster
from engine.twab import twab
from engine.types import EventKind, TokenEvent, WalletId
from sim.agents import Holder, whale_splitter
from sim.market import ConstantProductPool
from sim.world import WorldResult, run_world

CAP = ScoringParams().cap
ALPHA = RewardParams().alpha_per_day
HOLD, CHURN, UNDER = HoldParams(), ChurnParams(), UnderwaterParams()
SYBIL = SybilParams()
DAY = 86_400


@dataclass(frozen=True)
class Row:
    name: str
    condition: str
    passed: bool
    evidence: str


@dataclass
class BuyThenSell:
    """Buys once, later sells all tokens. Used to pump-and-dump around the farmer."""

    label: str
    funder: str
    buy_lamports: int
    buy_ts: int
    sell_ts: int
    tokens: int = 0
    sol: int = 0

    def __post_init__(self) -> None:
        from sim.agents import wallet_id

        self.wallet = wallet_id(self.label)
        self.funder_id = wallet_id(self.funder)

    def step(self, ts: int, pool: ConstantProductPool, books, clock) -> None:
        from sim.agents import _buy, _fund, _sell

        if ts == self.buy_ts and self.tokens == 0 and self.buy_lamports > 0:
            _fund(books, clock, ts, self.funder_id, self.wallet, self.buy_lamports)
            self.sol += self.buy_lamports
            got = _buy(books, clock, ts, pool, self.wallet, self.buy_lamports)
            self.sol -= self.buy_lamports
            self.tokens += got
            return
        if ts == self.sell_ts and self.tokens > 0:
            got = _sell(books, clock, ts, pool, self.wallet, self.tokens)
            self.sol += got
            self.tokens = 0


def _changes(events: list[TokenEvent], wallet: WalletId) -> list[tuple[int, int]]:
    bal = 0
    out: list[tuple[int, int]] = []
    for ev in sorted(events, key=lambda e: (e.slot, e.sig, e.ix)):
        delta = 0
        if ev.kind is EventKind.BUY and ev.dst == wallet:
            delta = ev.amount
        elif ev.kind is EventKind.SELL and ev.src == wallet:
            delta = -ev.amount
        elif ev.kind is EventKind.TRANSFER:
            if ev.dst == wallet:
                delta += ev.amount
            if ev.src == wallet:
                delta -= ev.amount
        if delta:
            bal += delta
            out.append((ev.ts, bal))
    return out


def _balances(events: list[TokenEvent], wallets: list[WalletId]) -> dict[WalletId, int]:
    ch: dict[WalletId, list[tuple[int, int]]] = {w: _changes(events, w) for w in wallets}
    return {w: (path[-1][1] if path else 0) for w, path in ch.items()}


def _twap_at(world: WorldResult, t: int, window_s: int = 3600) -> float:
    t0 = max(world.start_ts, t - window_s)
    t1 = max(t0 + 1, t)
    return world.pool.twap(t0, t1)


def score_clusters(world: WorldResult) -> tuple[dict[str, float], object, dict[str, float]]:
    """lots → TWAB → sybil cluster → H,F,U → score → capped shares."""
    holders = sorted(
        {e.dst for e in world.events if e.dst} | {e.src for e in world.events if e.src}
    )
    holders = [w for w in holders if w is not None]
    lots_map = build_lots(world.events, frozenset(), lambda t: _twap_at(world, t))
    bals = _balances(world.events, holders)
    evs = build_evidence(
        holders, world.events, world.sol_transfers, world.fundings, bals, frozenset(), SYBIL
    )
    clustered = cluster(holders, evs, SYBIL)
    t0, t1 = world.start_ts, world.t1
    twap_u = _twap_at(world, t1, int(UNDER.twap_hours * 3600))
    scores: dict[str, float] = {}
    for cid, members in clustered.members.items():
        lots = [lot for w in members for lot in lots_map.get(w, ())]
        bar = sum(twab(0, _changes(world.events, w), t0, t1) for w in members)
        v_buy = v_sell = 0
        for ev in world.events:
            if ev.kind is EventKind.BUY and ev.dst in members:
                v_buy += ev.amount
            elif ev.kind is EventKind.SELL and ev.src in members:
                v_sell += ev.amount
        hold = amount_weighted_hold(lots, t1, HOLD)
        churn = churn_factor(v_buy, v_sell, bar, CHURN)
        boost = underwater_boost(lots, twap_u, t1, UNDER) if lots else 1.0
        scores[cid] = score(bar, hold, churn, boost)
    shares = capped_shares(scores, CAP)
    return scores, clustered, shares


def _whale_cap_row(n: int, budget: int = 10**12) -> tuple[bool, str]:
    holders = [
        Holder(f"c{n}-{i}", f"f{n}-{i}", 10**9 * (100 if i == 0 else 1), 0) for i in range(n)
    ]
    world = run_world(seed=1000 + n, minutes=1, agents=list(holders))
    scores, _cl, shares = score_clusters(world)
    assert len(scores) == n, f"expected {n} clusters, got {len(scores)}"
    assert all(s <= CAP + 1e-12 for s in shares.values())
    payouts, rollover = allocate(budget, shares)
    ok_cons = sum(payouts.values()) + rollover == budget
    ok = ok_cons and len(shares) == n
    ev = f"n={n} clusters={len(scores)} max_pi={max(shares.values()):.6f} conserved={ok_cons}"
    return ok, ev


def row_whale_cap() -> Row:
    bits: list[str] = []
    passed = True
    for n in (5, 10, 19, 20, 100):
        ok, ev = _whale_cap_row(n)
        passed = passed and ok
        bits.append(ev)
    return Row(
        "whale_cap",
        "N in {5,10,19,20,100}: every π ≤ CAP, Σ payouts+rollover == R_e, loop terminates",
        passed,
        "; ".join(bits),
    )


def row_underwater() -> Row:
    # Shallow pool so a pump-and-dump moves the mid price.
    farmer = Holder("farmer", "funder-f", 5_000_000_000, buy_ts=60)
    pumper = BuyThenSell("pumper", "funder-p", 80_000_000_000, buy_ts=0, sell_ts=120)
    minutes = 48 * 60 + 30  # min_age_hours = 48h after the farmer's buy
    world = run_world(
        seed=7,
        minutes=minutes,
        agents=[pumper, farmer],
        token_reserve=200_000_000_000,
        sol_reserve=200_000_000_000,
    )
    lots_map = build_lots(world.events, frozenset(), lambda t: _twap_at(world, t))
    lots = lots_map.get(farmer.wallet, ())
    twap = _twap_at(world, world.t1, int(UNDER.twap_hours * 3600))
    boost = underwater_boost(lots, twap, world.t1, UNDER)
    # Net loss after costs: mark-to-market at end mid vs SOL spent on the buy.
    mtm = farmer.tokens * world.pool.mid_price() - farmer.buy_lamports
    ok = boost <= 1.5 + 1e-12 and mtm < 0
    ev = (
        f"U={boost:.6f} mid={world.pool.mid_price():.6f} twap={twap:.6f} "
        f"cost_tokens={farmer.tokens} mtm_lamports={mtm:.4f}"
    )
    return Row("underwater_farmer", "Boost ≤ 1.5× and a net loss after costs", ok, ev)


def row_sybil_split() -> Row:
    n, unit, field_n = 50, 10**9, 8
    field = [Holder(f"o{i}", f"fo{i}", unit, 0) for i in range(field_n)]
    split = whale_splitter("sybil-funder", n, unit, 0)
    control_whale = Holder("whale", "sybil-funder", unit * n, 0)
    treat = run_world(seed=21, minutes=1, agents=[*split, *field])
    # Fresh field agents for the control world (same labels → same wallet ids).
    field_c = [Holder(f"o{i}", f"fo{i}", unit, 0) for i in range(field_n)]
    ctrl = run_world(seed=22, minutes=1, agents=[control_whale, *field_c])
    budget = 10**12
    s_t, cl_t, sh_t = score_clusters(treat)
    s_c, cl_c, sh_c = score_clusters(ctrl)
    pay_t, _r_t = allocate(budget, sh_t)
    pay_c, _r_c = allocate(budget, sh_c)
    # The 50 split wallets must be one cluster (same first funder).
    split_ids = {h.wallet for h in split}
    cids = {cl_t.cluster_of[w] for w in split_ids}
    one_cluster = len(cids) == 1
    cid = next(iter(cids))
    one_ticket = len(cl_t.members[cid]) == n
    # Rewards of the split entity vs the unsplit whale; gain ≤ 0% (1 lamport floor slack).
    whale_cid = cl_c.cluster_of[control_whale.wallet]
    gain = pay_t[cid] - pay_c[whale_cid]
    gain_ok = gain <= 1
    cap_ok = sh_t[cid] <= CAP + 1e-12
    ok = one_cluster and one_ticket and gain_ok and cap_ok
    ev = (
        f"clusters={len(cids)} members={len(cl_t.members[cid])} "
        f"pay_split={pay_t[cid]} pay_whale={pay_c[whale_cid]} gain_lamports={gain} "
        f"pi={sh_t[cid]:.6f}"
    )
    return Row(
        "sybil_split",
        "50 wallets, same funder: one cluster, rewards gain ≤ 0%, 1 draw ticket, cap applies",
        ok,
        ev,
    )


def row_zero_inflow() -> Row:
    from sim.agents import Flipper

    # Busy day then a quiet day: volume should fall ≥ 90%. Then 7 zero-inflow epochs.
    flip = Flipper("flip", "ff", 10**10, start_ts=0, t1=86_400, per_day=5)
    idle = Holder("idle", "fi", 10**8, buy_ts=86_400 + 60)
    world = run_world(seed=3, minutes=48 * 60, agents=[flip, idle])
    mid = world.start_ts + DAY
    vol = [0, 0]
    for ev in world.events:
        amt = ev.lamports or 0
        vol[0 if ev.ts < mid else 1] += amt
    drop_ok = vol[0] > 0 and vol[1] <= 0.10 * vol[0]
    pot = 10**12
    first = seventh = 0
    for i in range(7):
        r = epoch_budget(pot, ALPHA, 24)
        if i == 0:
            first = r
        if i == 6:
            seventh = r
        pot -= r
    decay_ok = first > 0 and seventh >= 0.45 * first
    ev = (
        f"vol_busy={vol[0]} vol_quiet={vol[1]} drop_ok={drop_ok} "
        f"R1={first} R7={seventh} ratio={seventh / first if first else 0:.4f} "
        f"(pot inflow not wired: fees.py stub on main)"
    )
    return Row(
        "zero_inflow_pot_decay",
        "Volume −90% overnight; payouts ≥ 45% of the prior level after 7 zero-inflow days",
        drop_ok and decay_ok,
        ev,
    )


def row_draws_fairness() -> Row:
    # Deep pool, three holders ~1×, 4×, 9× so first-pick probs track √score ≈ 1:2:3.
    agents = [
        Holder("a", "fa", 1 * 10**10, 0),
        Holder("b", "fb", 4 * 10**10, 0),
        Holder("c", "fc", 9 * 10**10, 0),
    ]
    world = run_world(seed=42, minutes=1, agents=list(agents))
    scores, _cl, shares = score_clusters(world)
    assert len(scores) == 3
    payouts, _rollover = allocate(10**12, shares)
    doc_a = claims_document({w: max(1, payouts[_cl.cluster_of[w]]) for w in _cl.cluster_of}, 1)
    doc_b = claims_document(
        {w: max(1, payouts[_cl.cluster_of[w]]) for w in reversed(list(_cl.cluster_of))}, 1
    )
    identical = doc_a == doc_b
    weights = {cid: math.sqrt(s) for cid, s in scores.items() if s > 0}
    total = sum(weights.values())
    n = 8_000
    counts: Counter[str] = Counter()
    for i in range(n):
        counts[draw_winners(scores, i.to_bytes(8, "big"), 1)[0]] += 1
    chi2 = sum(
        (counts[c] - n * weights[c] / total) ** 2 / (n * weights[c] / total) for c in weights
    )
    # df=2, alpha=0.001 critical value 13.81551 (same as tests/test_draws.py).
    fair = chi2 <= 13.81551
    rounded = {k: round(v, 4) for k, v in scores.items()}
    ev = f"chi2={chi2:.3f} counts={dict(counts)} identical_claims={identical} scores={rounded}"
    return Row(
        "draws_fairness",
        "End-to-end: first-pick frequencies track √score; same inputs → identical claims doc",
        fair and identical,
        ev,
    )


SCENARIOS: tuple[Callable[[], Row], ...] = (
    row_whale_cap,
    row_underwater,
    row_sybil_split,
    row_zero_inflow,
    row_draws_fairness,
)


def run_all() -> list[Row]:
    return [fn() for fn in SCENARIOS]


def render_table(rows: list[Row]) -> str:
    lines = [
        "| scenario | pass condition | result | evidence |",
        "|---|---|---|---|",
    ]
    for r in rows:
        ev = r.evidence.replace("|", "/")
        lines.append(f"| {r.name} | {r.condition} | {'PASS' if r.passed else 'FAIL'} | {ev} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=None, help="Directory for acceptance_table.md")
    args = p.parse_args(argv)
    rows = run_all()
    table = render_table(rows)
    print(table)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "acceptance_table.md").write_text(table, encoding="utf-8")
        payload = [
            {"name": r.name, "condition": r.condition, "pass": r.passed, "evidence": r.evidence}
            for r in rows
        ]
        (args.out / "acceptance_table.json").write_text(json.dumps(payload, indent=2) + "\n")
    return 0 if all(r.passed for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
