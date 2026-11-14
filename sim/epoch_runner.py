"""Drive run_epoch from a simulator world and assert COIN_MATH §14 rows end-to-end."""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from engine.epoch import EpochInputs, EpochResult, EpochState, VestingEntry, empty_state, run_epoch
from engine.params import CoinParams
from sim.acceptance import BuyThenSell
from sim.agents import (
    Flipper,
    Holder,
    _buy,
    _fund,
    _sell,
    snapshot_sniper,
    wallet_id,
    whale_splitter,
)
from sim.market import ConstantProductPool
from sim.world import WorldResult, run_world

INFLOW = 10**12
SOL_USD = 100.0
DECIMALS = 9
DAY = 86_400
CAP = CoinParams().scoring.cap
DEFAULT_REPORT = Path("reports/sim_epoch_e2e.md")
SHALLOW = 200_000_000_000
PUMP_3X = 150_000_000_000  # ~3.05× end mid on SHALLOW after a 1 SOL dev buy


@dataclass(frozen=True)
class Row:
    name: str
    condition: str
    passed: bool
    evidence: str


@dataclass
class _HolderThenSell:
    """Buy once, then sell the whole bag at sell_ts. Used for the vest-forfeit row."""

    label: str
    funder: str
    buy_lamports: int
    buy_ts: int
    sell_ts: int
    tokens: int = 0
    _bought: bool = False

    def __post_init__(self) -> None:
        self.wallet = wallet_id(self.label)
        self.funder_id = wallet_id(self.funder)

    def step(self, ts: int, pool: ConstantProductPool, books, clock) -> None:
        if not self._bought and ts == self.buy_ts:
            _fund(books, clock, ts, self.funder_id, self.wallet, self.buy_lamports)
            self.tokens += _buy(books, clock, ts, pool, self.wallet, self.buy_lamports)
            self._bought = True
            return
        if ts == self.sell_ts and self.tokens > 0:
            _sell(books, clock, ts, pool, self.wallet, self.tokens)
            self.tokens = 0


def inputs_from_world(
    world: WorldResult,
    t0: int,
    t1: int,
    pot_inflow: int = INFLOW,
) -> EpochInputs:
    events = tuple(ev for ev in world.events if ev.ts < t1)
    slots = [ev.slot for ev in events] or [0]
    return EpochInputs(
        t0=t0,
        t1=t1,
        slot_range=(min(slots), max(slots)),
        events=events,
        sol_transfers=tuple(s for s in world.sol_transfers if s.ts < t1),
        fundings=tuple(f for f in world.fundings if f.ts < t1),
        prices=tuple(world.prices),
        decimals=DECIMALS,
        sol_usd=SOL_USD,
        pot_inflow=pot_inflow,
        excluded=frozenset(),
        hubs=frozenset(),
    )


def conservation_holds(prev: EpochState, inflow: int, result: EpochResult, nxt: EpochState) -> bool:
    left = prev.pot + inflow + sum(prev.carry.values())
    right = result.pot + sum(result.transferred_or_claimable.values()) + sum(nxt.carry.values())
    return left == right


def run_slice(
    world: WorldResult,
    t0: int,
    t1: int,
    params: CoinParams,
    prev: EpochState | None = None,
    pot_inflow: int = INFLOW,
) -> tuple[EpochResult, EpochState]:
    if t1 - t0 != params.epoch.hours * 3600:
        raise ValueError(f"window {t1 - t0}s != epoch.hours*{3600}")
    state = empty_state() if prev is None else prev
    result, nxt = run_epoch(inputs_from_world(world, t0, t1, pot_inflow), params, state)
    if not conservation_holds(state, pot_inflow, result, nxt):
        raise ValueError("conservation failed after run_epoch")
    return result, nxt


def _payout(result: EpochResult, wallet: str) -> int:
    return int(result.transferred_or_claimable.get(wallet, 0))


def _row_for_wallet(result: EpochResult, wallet: str):
    for row in result.scores:
        if row.cluster == wallet:
            return row
    return None


def scenario_honest(seed: int) -> Row:
    params = CoinParams()
    agents = [Holder(f"h{i}", f"fh{i}", 10**9, 0) for i in range(3)]
    world = run_world(seed, 24 * 60, list(agents))
    result, nxt = run_slice(world, 0, DAY, params)
    paid = [_payout(result, a.wallet) for a in agents]
    shares = [row.share for row in result.scores]
    ok = (
        all(p > 0 for p in paid)
        and all(s <= CAP + 1e-12 for s in shares)
        and max(paid) == min(paid)
        and nxt.pot < INFLOW
    )
    ev = f"payouts={paid} shares={[round(s, 4) for s in shares]} pot={nxt.pot} rail={result.rail}"
    return Row(
        "honest_holders",
        "3 equal holders: conservation, each paid, each π ≤ CAP, payouts equal",
        ok,
        ev,
    )


def scenario_sniper(seed: int) -> Row:
    params = CoinParams()
    holder = Holder("holder", "fh", 10**9, 0)
    sniper = snapshot_sniper("sniper", "fs", 10**9, t1=DAY)
    world = run_world(seed, 24 * 60, [holder, sniper])
    result, _nxt = run_slice(world, 0, DAY, params)
    h_pay, s_pay = _payout(result, holder.wallet), _payout(result, sniper.wallet)
    h_row, s_row = _row_for_wallet(result, holder.wallet), _row_for_wallet(result, sniper.wallet)
    h_score = 0.0 if h_row is None else h_row.score
    s_score = 0.0 if s_row is None else s_row.score
    # v0.3.3 §2 drops the 1h hold / USD gate. A 5-min sniper is still a tiny TWAB
    # (~5/1440 of a full-day holder). Compare scores, not payouts: the 5% cap
    # equalizes N=2 payouts. T_START=2h will zero this score in a later wiring PR.
    ratio = 0.0 if h_score == 0 else s_score / h_score
    ok = s_score == 0.0 or ratio <= 0.005
    ev = (
        f"holder_pay={h_pay} sniper_pay={s_pay} holder_score={h_score:.6f} "
        f"sniper_score={s_score:.6f} score_ratio={ratio:.6f}"
    )
    return Row(
        "sniper",
        "5-min sniper: score 0 or score ≤ 0.5% of a full-day holder",
        ok,
        ev,
    )


def scenario_flipper(seed: int) -> Row:
    params = CoinParams()
    holder = Holder("holder", "fh", 10**9, 0)
    flipper = Flipper("flipper", "ff", 10**9, 0, t1=2 * DAY, per_day=5)
    world = run_world(seed, 48 * 60, [holder, flipper])
    _r1, mid = run_slice(world, 0, DAY, params)
    result, _nxt = run_slice(world, DAY, 2 * DAY, params, prev=mid)
    h_row, f_row = _row_for_wallet(result, holder.wallet), _row_for_wallet(result, flipper.wallet)
    h_s = 0.0 if h_row is None else h_row.score
    f_s = 0.0 if f_row is None else f_row.score
    ratio = 0.0 if h_s == 0 else f_s / h_s
    # Compare scores, not payouts: with N=2 the 5% cap binds both shares to CAP.
    ok = ratio <= 0.10
    ev = f"holder_score={h_s:.4f} flipper_score={f_s:.4f} score_ratio={ratio:.6f}"
    return Row(
        "flipper",
        "5×/day flipper, epoch 2: score ≤ 10% of a holder (cap binds payouts at N=2)",
        ok,
        ev,
    )


def scenario_whale_cap(seed: int) -> Row:
    params = CoinParams()
    agents = [Holder(f"w{i}", f"fw{i}", 10**9 * (100 if i == 0 else 1), 0) for i in range(5)]
    world = run_world(seed, 24 * 60, list(agents))
    result, _nxt = run_slice(world, 0, DAY, params)
    shares = [row.share for row in result.scores]
    ok = len(shares) == 5 and all(s <= CAP + 1e-12 for s in shares)
    ev = f"n={len(shares)} max_pi={max(shares, default=0):.6f}"
    return Row(
        "whale_cap",
        "1 whale + 4 small holders: every π ≤ CAP, conservation holds",
        ok,
        ev,
    )


def scenario_sybil(seed: int) -> Row:
    params = CoinParams()
    field = [Holder(f"o{i}", f"fo{i}", 10**9, 0) for i in range(4)]
    split = whale_splitter("sybil-funder", 10, 10**9, 0)
    world = run_world(seed, 24 * 60, [*split, *field])
    result, _nxt = run_slice(world, 0, DAY, params)
    split_set = {h.wallet for h in split}
    # One cluster (lex-smallest id) should have twab ~10× a lone holder.
    lone = [row for row in result.scores if row.cluster not in split_set]
    typ = max((row.twab for row in lone), default=0.0)
    clustered = [row for row in result.scores if typ and row.twab >= 8 * typ]
    one = len(clustered) == 1
    members_paid = sum(1 for w in split_set if _payout(result, w) > 0)
    ok = one and members_paid == 10 and clustered[0].share <= CAP + 1e-12
    ev = (
        f"big_clusters={len(clustered)} split_paid={members_paid} "
        f"pi={clustered[0].share if clustered else 0:.6f} typ_twab={typ:.1f}"
    )
    return Row(
        "sybil_cluster",
        "10 wallets, same first funder: one cluster, all 10 paid a split of one capped share",
        ok,
        ev,
    )


def scenario_vest_pump(seed: int) -> Row:
    params = CoinParams()
    # Hold-only: 1h ~3× pump must not lift unlocked above u_time = 1/7.
    dev = Holder("dev", "fd", 10**9, 0)
    pumper = BuyThenSell("pumper", "fp", PUMP_3X, buy_ts=23 * 3600, sell_ts=-1)
    hold_w = run_world(seed, 24 * 60, [dev, pumper], token_reserve=SHALLOW, sol_reserve=SHALLOW)
    prev = EpochState(0, 0, {}, {}, {}, (VestingEntry(dev.wallet, dev.tokens, 1.0, 0),))
    _rh, nh = run_slice(hold_w, 0, DAY, params, prev=prev)
    unlocked = nh.unlocked.get(dev.wallet, 0.0)
    u_time = 1.0 / 7.0
    no_extra = abs(unlocked - u_time) < 1e-9

    # Sell the whole bag after the pump: soft-lock breach → forfeit, score 0.
    seller = _HolderThenSell("dev", "fd", 10**9, 0, sell_ts=23 * 3600 + 1800)
    pumper2 = BuyThenSell("pumper", "fp", PUMP_3X, buy_ts=23 * 3600, sell_ts=-1)
    sell_w = run_world(
        seed + 10_000, 24 * 60, [seller, pumper2], token_reserve=SHALLOW, sol_reserve=SHALLOW
    )
    bought = next(ev.amount for ev in sell_w.events if ev.dst == seller.wallet)
    prev2 = EpochState(0, 0, {}, {}, {}, (VestingEntry(seller.wallet, bought, 1.0, 0),))
    rf, nf = run_slice(sell_w, 0, DAY, params, prev=prev2)
    forfeited = seller.wallet in nf.forfeit_until
    srow = _row_for_wallet(rf, seller.wallet)
    score0 = srow is not None and srow.score == 0.0
    ok = no_extra and forfeited and score0
    ev = (
        f"unlocked={unlocked:.6f} u_time={u_time:.6f} forfeit={nf.forfeit_until} "
        f"dev_score={0.0 if srow is None else srow.score}"
    )
    return Row(
        "vest_pump",
        "1h ~3× pump: no extra unlock beyond u_time (1/7); selling the bag forfeits",
        ok,
        ev,
    )


def scenario_underwater(seed: int) -> Row:
    params = CoinParams()
    farmer = Holder("farmer", "ff", 5_000_000_000, buy_ts=60)
    pumper = BuyThenSell("pumper", "fp", 80_000_000_000, buy_ts=0, sell_ts=120)
    # Last 24h of a 50h world so the farmer lot is ≥ 48h old (min_age_hours).
    world = run_world(seed, 50 * 60, [pumper, farmer], token_reserve=SHALLOW, sol_reserve=SHALLOW)
    result, _nxt = run_slice(world, 26 * 3600, 50 * 3600, params)
    row = _row_for_wallet(result, farmer.wallet)
    mid = world.pool.mid_price()
    mtm = farmer.tokens * mid - farmer.buy_lamports
    boost = 1.0 if row is None else row.boost
    ok = row is not None and 1.0 < boost <= 1.5 + 1e-12 and mtm < 0
    ev = f"U={boost:.4f} mtm={mtm:.1f} mid={mid:.4f} farmer_pay={_payout(result, farmer.wallet)}"
    return Row(
        "underwater",
        "Farmer buys near the top, 48h+ later: 1 < U ≤ 1.5 and mark-to-market loss",
        ok,
        ev,
    )


def scenario_rewards_off(seed: int) -> Row:
    base = CoinParams()
    params = base.model_copy(update={"rewards": base.rewards.model_copy(update={"enabled": False})})
    agents = [Holder(f"h{i}", f"fh{i}", 10**9, 0) for i in range(2)]
    world = run_world(seed, 24 * 60, list(agents))
    result, nxt = run_slice(world, 0, DAY, params)
    ok = result.payouts == {} and result.transferred_or_claimable == {} and nxt.pot == INFLOW
    ev = f"payouts={dict(result.payouts)} pot={nxt.pot} rail={result.rail}"
    return Row(
        "rewards_disabled",
        "rewards.enabled=False: zero payouts, pot += inflow only, conservation holds",
        ok,
        ev,
    )


SCENARIOS: tuple[tuple[str, Callable[[int], Row]], ...] = (
    ("honest_holders", scenario_honest),
    ("sniper", scenario_sniper),
    ("flipper", scenario_flipper),
    ("whale_cap", scenario_whale_cap),
    ("sybil_cluster", scenario_sybil),
    ("vest_pump", scenario_vest_pump),
    ("underwater", scenario_underwater),
    ("rewards_disabled", scenario_rewards_off),
)


def run_e2e(seeds: int) -> tuple[list[Row], float]:
    if seeds <= 0:
        raise ValueError("seeds must be > 0")
    t0 = time.perf_counter()
    rows: list[Row] = []
    for name, fn in SCENARIOS:
        n_ok = 0
        condition = ""
        first_fail = ""
        sample = ""
        for seed in range(seeds):
            row = fn(seed)
            condition = row.condition
            bit = f"s{seed}:{row.evidence}"
            if row.passed:
                n_ok += 1
                if not sample:
                    sample = bit
            else:
                first_fail = first_fail or bit + " FAIL"
        passed = n_ok == seeds
        ev = f"{n_ok}/{seeds} passed. " + (first_fail or sample)
        rows.append(Row(name, condition, passed, ev))
    return rows, time.perf_counter() - t0


def render_table(rows: Sequence[Row], elapsed: float, seeds: int) -> str:
    lines = [
        "# Full-epoch simulator e2e (run_epoch)",
        "",
        "Each row drives the real `engine.epoch.run_epoch` from a `sim` world. "
        "Defaults are unchanged. Conservation is the §8 identity, also asserted in the runner.",
        "",
        f"Seeds: {seeds}. Wall time: {elapsed:.2f}s.",
        "",
        "| scenario | pass condition | result | evidence |",
        "|---|---|---|---|",
    ]
    for row in rows:
        ev = row.evidence.replace("|", "/")
        flag = "PASS" if row.passed else "FAIL"
        lines.append(f"| {row.name} | {row.condition} | {flag} | {ev} |")
    fails = [row.name for row in rows if not row.passed]
    lines.append("")
    if fails:
        lines.append(f"**FAIL:** {', '.join(fails)}. Engine math/defaults were not changed.")
    else:
        lines.append("All rows passed.")
    lines.append("")
    return chr(10).join(lines)


def write_report(path: Path | None = None, seeds: int = 10) -> tuple[Path, list[Row], float]:
    dest = DEFAULT_REPORT if path is None else Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows, elapsed = run_e2e(seeds)
    dest.write_text(render_table(rows, elapsed, seeds), encoding="utf-8")
    return dest, rows, elapsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim.epoch_runner")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    if args.seeds <= 0:
        raise SystemExit("--seeds must be > 0")
    dest, rows, elapsed = write_report(args.out, args.seeds)
    print(render_table(rows, elapsed, args.seeds))
    print(dest)
    return 0 if all(row.passed for row in rows) and elapsed < 60 else 1


if __name__ == "__main__":
    raise SystemExit(main())
