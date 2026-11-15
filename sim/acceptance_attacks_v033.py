"""COIN_MATH v0.3.3 §14 attack rows (#84 step 2): sybil splits and forced merges, dust,
soft-vesting escapes, circular moves, price windows. Same harness as sim.acceptance_v033.
Pump/dump against arbitrage agents (attacker PnL) is step 2b: it needs the market model.
"""

from __future__ import annotations

import random
from dataclasses import replace
from fractions import Fraction

import sim.acceptance_v033 as acc
from engine.epoch import EpochResult, EpochState, VestingEntry, empty_state, run_epoch
from engine.prices import HarmonicOracle, ReservePoint, harmonic_mean
from sim.acceptance_v033 import DAY, HOUR, T0, TOK, Outcome, Trades, _same, _score, _w

SOL = 10**9


def _clusters(res: EpochResult) -> set[str]:
    return {r.cluster for r in res.scores}


def _alone(res: EpochResult, *ws: str) -> bool:
    """Each wallet is its own cluster (cluster id = wallet, §7 smallest holder)."""
    return set(ws) <= _clusters(res)


def _run(tr: Trades, prev: EpochState | None = None, **kw) -> tuple[EpochResult, EpochState]:
    return run_epoch(replace(tr.inputs(), **kw), acc.PARAMS, prev or empty_state())


def row_whale_split_funded(rng: random.Random) -> Outcome:
    """Whale splits into 50 wallets funded from one wallet: one cluster, no gain, cap applies."""
    whale, others = _w(rng, "whale"), [_w(rng, f"o{i}") for i in range(20)]
    one, split = Trades("ws1"), Trades("wsn")
    bag = rng.randint(10**6, 10**7) * TOK
    sizes = [rng.randint(1_000, 10**5) * TOK for _ in others]
    for tr in (one, split):
        for o, size in zip(others, sizes, strict=True):
            tr.buy(o, size, T0 - 20 * DAY)
    one.buy(whale, bag, T0 - 20 * DAY)
    farm = [_w(rng, f"farm{i}") for i in range(50)]
    for i, f in enumerate(farm):
        split.fund(whale, f, 10 * SOL, T0 - 21 * DAY + i)
        split.buy(f, bag // 50, T0 - 20 * DAY + 60 + i)
    r1, _ = _run(one)
    rn, _ = _run(split)
    p1 = r1.payouts.get(whale, 0)
    pn = sum(rn.payouts.get(f, 0) for f in farm)
    merged = len(_clusters(rn) & set(farm)) <= 1
    capped = max(r.share for r in rn.scores) <= 0.05 + 1e-12
    return Outcome(merged and capped and pn <= p1, f"single={p1} split={pn} one_cluster={merged}")


def row_dust(rng: random.Random) -> Outcome:
    """Attacker sends tokens and SOL to a victim: victim's score, eligibility, payout not lower."""
    v, atk, other = _w(rng, "victim"), _w(rng, "atk"), _w(rng, "other")
    sizes = [rng.randint(1_000, 10**5) * TOK for _ in range(2)]
    base, dusted = Trades("d0"), Trades("d1")
    for tr in (base, dusted):
        tr.buy(v, sizes[0], T0 - 15 * DAY)
        tr.buy(other, sizes[1], T0 - 15 * DAY)
    dusted.buy(atk, 10**4 * TOK, T0 - 16 * DAY)
    for _ in range(rng.randint(1, 5)):
        t = T0 - rng.randint(0, 14 * DAY)
        dusted.send(atk, v, rng.randint(1, 10**3) * TOK, t)
        dusted.fund(atk, v, rng.randint(1, 10**9), t + 1)
    (r0, _), (r1, _) = _run(base), _run(dusted)
    unmerged = _alone(r1, v, atk)
    s0, s1 = _score(r0, v), _score(r1, v)
    ok = unmerged and (s1 >= s0 or _same(s0, s1))
    return Outcome(ok, f"score {float(s0):.0f}→{float(s1):.0f} unmerged={unmerged}")


def row_forced_merge_free(rng: random.Random) -> Outcome:
    """Transfers to the victim, copy trades, same destination: no merge."""
    tr, v, atk = Trades("fmf"), _w(rng, "fv"), _w(rng, "fa")
    for k in range(4):  # copy trades: same second, same size, ≥ 3 occasions (L4 only)
        amt = rng.randint(100, 10**4) * TOK
        tr.buy(v, amt, T0 - (10 - k) * DAY)
        tr.buy(atk, amt, T0 - (10 - k) * DAY)
    for d in (3, 2):  # one-way token transfers on 2 days (L3)
        tr.send(atk, v, TOK, T0 - d * DAY)
    res, _ = _run(tr)
    return Outcome(_alone(res, v, atk), f"clusters={len(_clusters(res))}")


def row_forced_merge_funding(rng: random.Random) -> Outcome:
    """Attacker SOL before the victim buys: merge only at ≥ 50% of inflows AND spend; cost shown."""
    v, atk, cex = _w(rng, "mv"), _w(rng, "ma"), _w(rng, "cex")
    spend = rng.randint(1, 50) * SOL
    below, at = Trades("mb"), Trades("ma")
    for tr, gift in ((below, spend // 2 - 1), (at, spend)):
        tr.buy(atk, 10**4 * TOK, T0 - 30 * DAY)
        tr.fund(cex, v, spend, T0 - 21 * DAY)
        tr.fund(atk, v, gift, T0 - 21 * DAY + 1)
        tr.events.append(replace(_buy_event(tr, v, spend * 10**6, T0 - 20 * DAY), lamports=spend))
    rb, _ = _run(below)
    ra, _ = _run(at)
    ok = _alone(rb, v, atk) and not _alone(ra, v, atk)
    return Outcome(ok, f"no merge at {spend // 2 - 1} lamports; merge costs ≥ {spend} lamports")


def _buy_event(tr: Trades, w: str, amount: int, ts: int):
    tr.buy(w, amount, ts)
    return tr.events.pop()


def row_chain_only_ab(rng: random.Random) -> Outcome:
    """A–B co-signed, B–C one transfer, C–D co-trades: only A–B merged."""
    tr = Trades("chain")
    a, b, c, d = sorted(_w(rng, x) for x in "abcd")
    for w in (a, b, c, d):
        tr.buy(w, rng.randint(1_000, 10**4) * TOK, T0 - 30 * DAY)
    tr.send(b, c, TOK, T0 - 5 * DAY)
    for k in range(3):
        tr.buy(c, 50 * TOK, T0 - (9 - k) * DAY)
        tr.buy(d, 50 * TOK, T0 - (9 - k) * DAY)
    res, _ = _run(tr, signers={"cosig": frozenset({a, b})})
    ok = _clusters(res) == {a, c, d}
    return Outcome(ok, f"clusters={len(_clusters(res))} (want 3)")


def row_vest_sell(rng: random.Random) -> Outcome:
    """Soft vesting: selling locked tokens → forfeit."""
    tr, v = Trades("vs"), _w(rng, "vs")
    amt = rng.randint(1_000, 10**5) * TOK
    tr.buy(v, amt, T0 - HOUR)
    tr.sell(v, amt // 2, T0 + rng.randint(0, DAY - 1))
    prev = EpochState(0, 0, {}, {}, {}, (VestingEntry(v, amt, "1/1000000", T0 - HOUR),))
    _, nxt = run_epoch(tr.inputs(), acc.PARAMS, prev)
    return Outcome(v in nxt.forfeit_until, f"forfeit_until={nxt.forfeit_until.get(v)}")


def row_vest_three_hops(rng: random.Random) -> Outcome:
    """Locked tokens out through 3 wallets: forfeit; tainted at every hop; no gain vs holding.

    "Gain" is the attacker group's total score (the tokens' earning power). Payouts also move
    with S when a forfeited cluster drops out, for every holder alike; that is not the tokens'.
    """
    v, h1, h2, h3 = (_w(rng, x) for x in ("v", "h1", "h2", "h3"))
    amt = rng.randint(1_000, 10**5) * TOK
    hold, hop = Trades("vh0"), Trades("vh3")
    for tr in (hold, hop):
        tr.buy(v, amt, T0 - 3 * DAY)
        for i, h in enumerate((h1, h2, h3)):
            tr.buy(h, TOK * 1_000, T0 - 4 * DAY + i)  # each hop already holds its own lot
    t = T0 - 2 * DAY
    for src, dst in ((v, h1), (h1, h2), (h2, h3)):
        hop.send(src, dst, amt, t)
        t += 600
    prev = EpochState(0, 0, {}, {}, {}, (VestingEntry(v, amt, "1/1000000", T0 - 3 * DAY),))
    (r0, _), (r1, n1) = (run_epoch(x.inputs(), acc.PARAMS, prev) for x in (hold, hop))
    group = (v, h1, h2, h3)
    s0, s1 = sum(_score(r0, w) for w in group), sum(_score(r1, w) for w in group)
    own_only = all(_same(_score(r1, h), _score(r0, h)) for h in (h1, h2, h3))  # tainted: 0 extra
    ok = v in n1.forfeit_until and own_only and s1 <= s0
    return Outcome(ok, f"forfeit={v in n1.forfeit_until} score {float(s0):.0f}→{float(s1):.0f}")


def row_circular(rng: random.Random) -> Outcome:
    """A→B→C→A inside and across clusters: no gain in score or age."""
    a, b, c = (_w(rng, x) for x in "abc")
    amt = rng.randint(1_000, 10**5) * TOK
    still, loop = Trades("c0"), Trades("c1")
    for tr in (still, loop):
        for w in (a, b, c):
            tr.buy(w, amt, T0 - 40 * DAY)
    t = T0 - rng.randint(1, 10) * DAY
    for src, dst in ((a, b), (b, c), (c, a)):
        loop.send(src, dst, amt, t)
        t += 60
    s0 = sum(_score(_run(still)[0], w) for w in (a, b, c))
    s1 = sum(_score(_run(loop)[0], w) for w in (a, b, c))
    return Outcome(s1 <= s0 or _same(s1, s0), f"score {float(s0):.0f}→{float(s1):.0f}")


def row_move_bag_new_wallet(rng: random.Random) -> Outcome:
    """Whole bag to a new wallet funded by the old one: age and cost preserved (S2 merge)."""
    old, new = _w(rng, "old"), _w(rng, "new")
    amt = rng.randint(1_000, 10**5) * TOK
    stay, move = Trades("m0"), Trades("m1")
    for tr in (stay, move):
        tr.buy(old, amt, T0 - 60 * DAY)
    move.fund(old, new, SOL, T0 - 9 * DAY)
    move.buy(new, TOK, T0 - 9 * DAY + 10)  # the funded buy makes the S2 edge
    move.send(old, new, amt, T0 - 8 * DAY)
    s0 = _score(_run(stay)[0], old)
    r1, _ = _run(move)
    s1 = sum(Fraction(r.score) for r in r1.scores)  # + the 1-token funded buy's own score
    merged = len(r1.scores) == 1
    ok = merged and (s1 >= s0 or _same(s1, s0))
    return Outcome(ok, f"score {float(s0):.0f}→{float(s1):.0f} merged={merged}")


def row_pump_bound(rng: random.Random) -> Outcome:
    """Pump of any size for ≤ 1h: P̃_h ≤ (24/23)·H_rest on random price histories."""
    t_end, pts, t = 10 * DAY, [], 0
    while t < t_end:
        q = rng.randint(100, 10**4) * SOL
        pts.append(ReservePoint(t, q, q * rng.randint(10**5, 10**7)))
        t += rng.randint(60, 4 * HOUR)
    tau = rng.randint(1, HOUR)
    start = t_end - rng.randint(tau, DAY)
    base = harmonic_mean(pts, t_end - DAY, t_end)
    pumped = [p for p in pts if not start <= p.ts < start + tau]
    q = 10**6 * SOL
    pumped += [ReservePoint(start, q, max(1, q // (10**3 * rng.randint(1, 10**6)))),
               ReservePoint(start + tau, *_state_at(pts, start + tau))]  # fmt: skip
    pumped = sorted({p.ts: p for p in pumped}.values(), key=lambda p: p.ts)
    h = HarmonicOracle(pumped, DAY, 1)(t_end)
    bound = Fraction(DAY, DAY - tau) * _h_rest(pts, t_end, start, tau)
    ok = h is not None and h <= bound
    return Outcome(
        ok, f"tau={tau}s P̃h/base={float(h / base):.4f} bound/base={float(bound / base):.4f}"
    )


def _state_at(pts: list[ReservePoint], t: int) -> tuple[int, int]:
    p = max((p for p in pts if p.ts <= t), key=lambda p: p.ts)
    return p.reserve_quote, p.reserve_base


def _h_rest(pts: list[ReservePoint], t_end: int, start: int, tau: int) -> Fraction:
    """Harmonic mean of the window's seconds outside [start, start + tau)."""
    w0, recip = t_end - DAY, Fraction(0)
    for a, b in ((w0, start), (start + tau, t_end)):
        if b > a:
            recip += (b - a) / harmonic_mean(pts, a, b)
    return Fraction(DAY - tau) / recip


ROWS = (
    ("Whale splits into 50 funded wallets", "one cluster, no gain, cap", row_whale_split_funded),
    ("Dust attack (tokens + SOL)", "victim not merged, score not lower", row_dust),
    ("Forced merge, free actions", "no merge", row_forced_merge_free),
    ("Forced merge, funding", "merge only at ≥ 50% inflow + spend", row_forced_merge_funding),
    ("Chain A–B co-signed, B–C, C–D", "only A–B merged", row_chain_only_ab),
    ("Soft vesting: selling locked tokens", "forfeit applied", row_vest_sell),
    ("Soft vesting: out via 3 wallets", "forfeit; tainted every hop; no gain", row_vest_three_hops),
    ("Circular transfers A→B→C→A", "no gain in score or age", row_circular),
    ("Whole bag to a new funded wallet", "age and cost preserved", row_move_bag_new_wallet),
    ("Pump ≤ 1h, random histories", "P̃_h ≤ (24/23)·H_rest", row_pump_bound),
)  # fmt: skip
