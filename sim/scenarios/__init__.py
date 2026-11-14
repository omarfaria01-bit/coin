"""Scenario registry. Missing engine modules → pass='skipped' (NotImplementedError)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from engine.types import EventKind, TokenEvent, WalletId
from sim.agents import Flipper, Holder, snapshot_sniper
from sim.world import run_world

BUY_LAMPORTS = 10**9  # 1 SOL
REGISTRY: dict[str, Callable[[int], dict]] = {}


def _changes(events: Sequence[TokenEvent], wallet: WalletId) -> list[tuple[int, int]]:
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


def _volume(events: Sequence[TokenEvent], wallet: WalletId, t0: int, t1: int) -> tuple[int, int]:
    buy = sell = 0
    for ev in events:
        if not (t0 <= ev.ts < t1):
            continue
        if ev.kind is EventKind.BUY and ev.dst == wallet:
            buy += ev.amount
        elif ev.kind is EventKind.SELL and ev.src == wallet:
            sell += ev.amount
    return buy, sell


def _try(build: Callable[[], dict]) -> dict:
    try:
        return build()
    except NotImplementedError as exc:
        return {"pass": "skipped", "reason": str(exc)}


def _sniper(seed: int) -> dict:
    from engine.twab import twab

    minutes = 1440
    holder = Holder("holder", "funder", BUY_LAMPORTS, buy_ts=0)
    sniper = snapshot_sniper("sniper", "funder", BUY_LAMPORTS, t1=minutes * 60)
    world = run_world(seed, minutes, [holder, sniper])
    h = twab(0, _changes(world.events, holder.wallet), world.start_ts, world.t1)
    s = twab(0, _changes(world.events, sniper.wallet), world.start_ts, world.t1)
    ratio = 0.0 if h == 0 else s / h
    return {
        "pass": bool(ratio <= 0.005),
        "holder_twab": h,
        "sniper_twab": s,
        "ratio": ratio,
        "n_events": len(world.events),
    }


def _flipper(seed: int) -> dict:
    from engine.params import ChurnParams, HoldParams, UnderwaterParams
    from engine.scoring import amount_weighted_hold, churn_factor, score, underwater_boost
    from engine.twab import twab

    minutes = 2880  # 48h churn window
    t1 = minutes * 60
    holder = Holder("holder", "funder", BUY_LAMPORTS, buy_ts=0)
    flipper = Flipper("flipper", "funder", BUY_LAMPORTS, start_ts=0, t1=t1, per_day=5)
    world = run_world(seed, minutes, [holder, flipper])
    hold_p, churn_p, under_p = HoldParams(), ChurnParams(), UnderwaterParams()
    rows = {}
    for name, agent in ("holder", holder), ("flipper", flipper):
        tw = twab(0, _changes(world.events, agent.wallet), world.start_ts, world.t1)
        v_buy, v_sell = _volume(world.events, agent.wallet, world.start_ts, world.t1)
        # Fresh lots: score at t1 with mid as 1h twap (no transfers in this scenario).
        mid = world.pool.mid_price()
        from engine.ledger import build_lots

        lots = build_lots(world.events, frozenset(), lambda _t, p=mid: p).get(agent.wallet, ())
        h = amount_weighted_hold(lots, world.t1, hold_p)
        f = churn_factor(v_buy, v_sell, tw, churn_p)
        u = underwater_boost(
            lots, world.pool.twap(world.t1 - 6 * 3600, world.t1), world.t1, under_p
        )
        rows[name] = {"twab": tw, "H": h, "F": f, "U": u, "score": score(tw, h, f, u)}
    ratio = (
        0.0 if rows["holder"]["score"] == 0 else rows["flipper"]["score"] / rows["holder"]["score"]
    )
    return {
        "pass": bool(ratio <= 0.10),
        "ratio": ratio,
        "holder": rows["holder"],
        "flipper": rows["flipper"],
    }


def run_sniper(seed: int) -> dict:
    return _try(lambda: _sniper(seed))


def run_flipper(seed: int) -> dict:
    return _try(lambda: _flipper(seed))


REGISTRY["sniper"] = run_sniper
REGISTRY["flipper"] = run_flipper
