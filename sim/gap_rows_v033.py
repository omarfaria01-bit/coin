"""Offline rows for the non-flag §14 GAPs (#133): ingest-layer checks on the pure engine.

Every row drives the same public functions ``run_epoch`` calls (events clock, pool reserves,
sybil clustering, overrides), so none of them needs RPC, a wallet or a wall clock. Rows that
still need the network or a new model are listed with a reason in ``sim.report_v033.GAPS``.
The market-level arbitrage rows (#136) live in ``sim.arbitrage_v033`` and are appended here.
"""

from __future__ import annotations

import random
from dataclasses import replace
from fractions import Fraction

import sim.acceptance_v033 as acc
from engine.epoch import empty_state, run_epoch
from engine.events import SlotTime, clamp_block_times
from engine.prices import (
    HarmonicOracle,
    ReservePoint,
    arithmetic_mean,
    is_trusted_second,
    price_at,
    untrusted_fraction,
)
from engine.sybil_v033 import cluster, l4_co_trades, s2_funded_buys, transfer_links
from engine.types import EventKind, TokenEvent
from sim.acceptance_v033 import DAY, T0, T1, TOK, Outcome, Trades, _same, _score, _w
from sim.arbitrage_v033 import ROWS as ARB_ROWS

SOL = 10**9


def _run(tr: Trades, t0: int = T0, **kw) -> tuple:
    return run_epoch(replace(tr.inputs(t0), **kw), acc.PARAMS, empty_state())


def _clusters(res) -> set[str]:
    return {r.cluster for r in res.scores}


# --------------------------------------------------------------------------- rows


def row_same_second(rng: random.Random) -> Outcome:
    """Buy and sell in the same second: intra-second states get zero weight; p(t) is the
    end-of-second reserve price, fees included."""
    deep = 1_000 * SOL
    pts = (ReservePoint(T0 - 10, deep, 10**12), ReservePoint(T0 - 9, 2 * deep, 10**12))
    # One reserve point per second: the mean over two seconds is (p0 + p1) / 2 whatever
    # happened inside either second, and p(t) is the end-of-second state.
    p_end = price_at(pts, T0 - 9)
    mean = arithmetic_mean(pts, T0 - 10, T0 - 8)
    w, amt = _w(rng, "ss"), rng.randint(1_000, 10**5) * TOK
    base, churn = Trades("ss0"), Trades("ss1")
    for tr in (base, churn):
        tr.buy(w, amt, T0 - 30 * DAY)
    for k in range(1, 6):
        ts = T0 - 20 * DAY + k * 1_000
        slot = ts + 10**7
        # Same slot and signature, buy ix 0 then sell ix 1: the round trip never crosses a
        # whole second of lot time, so it adds no score.
        for ix, (src, dst) in enumerate(((None, w), (w, None)), start=0):
            kind = EventKind.BUY if src is None else EventKind.SELL
            churn.events.append(TokenEvent(slot, ts, f"ss-rt-{k}", ix, kind, src, dst, TOK, TOK, w))
    s0, s1 = _score(_run(base)[0], w), _score(_run(churn)[0], w)
    ok = _same(s0, s1) and p_end == Fraction(2 * deep, 10**12)
    ok = ok and mean == (p_end + Fraction(deep, 10**12)) / 2
    return Outcome(ok, f"round trips 0; p(t)=end-of-second={float(p_end):.1e}; score same={ok}")


def row_trust_threshold(rng: random.Random) -> Outcome:
    """Pool depth below the trust threshold: no untrusted price read, boost off, base
    rewards and eligibility unaffected."""
    d_trust = acc.PARAMS.prices.d_trust_lamports
    thin, deep = 10 * SOL, 300 * SOL
    w, amt = _w(rng, "td"), rng.randint(1_000, 10**5) * TOK
    tr = Trades("td")
    tr.buy(w, amt, T0 - 10 * DAY)
    plain, _ = _run(tr)
    thin_pts = (ReservePoint(T0 - DAY, thin, thin // 3),)
    thin_res, _ = _run(tr, reserves=thin_pts)
    base = [(r.cluster, r.twab, r.score) for r in plain.scores]
    got = [(r.cluster, r.twab, r.score) for r in thin_res.scores]
    untrusted = untrusted_fraction(thin_pts, T0, T1, d_trust)
    paused = HarmonicOracle(thin_pts, DAY, d_trust)(T1) is None
    ok = (
        not is_trusted_second(thin, thin // 3, d_trust)
        and is_trusted_second(deep, deep // 3, d_trust)
        and untrusted == 1
        and paused
        and base == got
        and dict(plain.payouts) == dict(thin_res.payouts)
    )
    return Outcome(
        ok,
        f"thin untrusted={float(untrusted):.1f} unlock=None; payouts/score equal={base == got}",
    )


def row_clock_clamp(rng: random.Random) -> Outcome:
    """Missing/decreasing block time and skipped slots: the documented clamping rule gives
    the clean log's clock, so the epoch output is the same."""
    dirty = [
        SlotTime(100, 1_000),
        SlotTime(101, None),  # missing: takes 1000
        SlotTime(103, 1_060),  # skipped slot 102
        SlotTime(106, 1_020),  # decreasing: clamped to 1060
        SlotTime(107, None),  # missing: takes 1060
        SlotTime(109, 1_180),  # skipped slot 108
    ]
    clamped = clamp_block_times(dirty)
    clean = [SlotTime(slot, ts) for slot, ts in clamped.items()]  # the same clock, no damage
    ok = list(clamped.values()) == [1_000, 1_000, 1_060, 1_060, 1_060, 1_180]
    ok = ok and clamp_block_times(clean) == clamped
    # The events carry the clamped clock, as the adapters do; then the clean log with the
    # same effective seconds must produce the same epoch.
    a, b = _w(rng, "clk-a"), _w(rng, "clk-b")
    clean_tr, dirty_tr = Trades("clk"), Trades("clk")  # same sigs: only the clock differs
    times = list(clamped.values())
    for tr in (clean_tr, dirty_tr):
        tr.buy(a, TOK * 1_000, times[0])
        tr.buy(b, TOK * 2_000, times[1])
        tr.sell(a, TOK * 500, times[-1])
    r0, r1 = _run(clean_tr)[0], _run(dirty_tr)[0]
    ok = ok and r0.inputs_hash == r1.inputs_hash and dict(r0.payouts) == dict(r1.payouts)
    secs = len(set(clamped.values()))
    return Outcome(ok, f"{len(dirty)} slots → {secs} seconds; same epoch={ok}")


def row_shared_payer(rng: random.Random) -> Outcome:
    """Same fee-paying app plus one-sided signals: no merge; the payer is in the review list."""
    ws = [_w(rng, f"app{i}") for i in range(5)]
    atk = _w(rng, "app-atk")
    tr = Trades("app")
    for i, w in enumerate(ws):
        tr.buy(w, rng.randint(1_000, 10**4) * TOK, T0 - (30 - i) * DAY)
    tr.buy(atk, rng.randint(10**4, 10**5) * TOK, T0 - 30 * DAY)
    # One-sided signals from the attacker: L3 on two days and L4 on three occasions.
    tr.send(atk, ws[0], TOK, T0 - 10 * DAY)
    tr.send(atk, ws[0], TOK, T0 - 9 * DAY)
    for k in range(3):
        ts = T0 - (8 - k) * DAY
        tr.buy(ws[0], 100 * TOK, ts)
        tr.buy(atk, 100 * TOK, ts + 1)
    events = tuple(replace(e, fee_payer="APP") for e in tr.events)
    holders = frozenset([*ws, atk])
    edges = [
        *s2_funded_buys(events, tr.sols, frozenset()),
        *transfer_links(events, tr.sols, frozenset()),
        *l4_co_trades(events, frozenset()),
    ]
    res = cluster(holders, edges, frozenset(), events)
    merged = res.cluster_of[ws[0]] == res.cluster_of[atk]
    ok = len(res.members) == 6 and not merged and "APP" in res.shared_payers
    return Outcome(ok, f"clusters={len(res.members)} merged={merged} review={res.shared_payers}")


def row_single_transfer(rng: random.Random) -> Outcome:
    """One commercial transfer between two owners: no merge."""
    a, b = _w(rng, "st-a"), _w(rng, "st-b")
    amt = rng.randint(1_000, 10**5) * TOK
    tr = Trades("st")
    tr.buy(a, amt, T0 - 30 * DAY)
    tr.send(a, b, amt // 2, T0 - 5 * DAY)
    res, _ = _run(tr)
    ok = _clusters(res) == {a, b}
    return Outcome(ok, f"clusters={len(_clusters(res))} (want 2)")


def row_false_merge(rng: random.Random) -> Outcome:
    """False merge of two independent clusters (an S3 override): tokens that never moved
    score exactly the same; cap damage is measured and within the first target."""
    a, b = _w(rng, "fm-a"), _w(rng, "fm-b")
    tr = Trades("fm")
    tr.buy(a, TOK * 1_000, T0 - 30 * DAY)
    tr.buy(b, TOK * 1_000, T0 - 30 * DAY)
    for i in range(40):  # the rest of the supply, so a + b stay well under the 5% cap
        tr.buy(_w(rng, f"fm-o{i}"), rng.randint(10**5, 10**6) * TOK, T0 - 30 * DAY)
    correct, _ = _run(tr)
    forced, _ = _run(tr, overrides=((a, b, "review-1"),))
    s_a, s_b = _score(correct, a), _score(correct, b)
    s_ab = sum(_score(forced, w) for w in (a, b))
    paid_correct = correct.payouts.get(a, 0) + correct.payouts.get(b, 0)
    paid_forced = forced.payouts.get(a, 0) + forced.payouts.get(b, 0)
    damage = abs(paid_forced - paid_correct) / paid_correct if paid_correct else 0.0
    ok = len(_clusters(correct)) == 42 and len(_clusters(forced)) == 41
    ok = ok and _same(s_ab, s_a + s_b) and damage <= 0.20
    return Outcome(ok, f"score same={_same(s_ab, s_a + s_b)} damage={damage:.1%} ≤ 20%")


def row_sybil_recall(rng: random.Random) -> Outcome:
    """Sybil recall: self-funded farms grouped (≥ 95%); CEX-funded farms are the residual."""
    tr, holders, funders, cex = Trades("rec"), [], [], []
    for i in range(4):
        f = _w(rng, f"rec-f{i}")
        funders.append(f)
        for j in range(3):
            w = _w(rng, f"rec-f{i}w{j}")
            amount = rng.randint(1_000, 10**4) * TOK
            tr.fund(f, w, amount // 10**6, T0 - 20 * DAY + i * 100 + j)
            tr.buy(w, amount, T0 - 20 * DAY + i * 100 + j + 1)
            holders.append(w)
    for i in range(4):
        for j in range(3):
            w = _w(rng, f"rec-c{i}w{j}")
            amount = rng.randint(1_000, 10**4) * TOK
            tr.fund("CEX", w, amount // 10**6, T0 - 20 * DAY + 500 + i * 100 + j)
            tr.buy(w, amount, T0 - 20 * DAY + 500 + i * 100 + j + 1)
            holders.append(w)
            cex.append(w)
    hubs = frozenset({"CEX"})
    edges = s2_funded_buys(tr.events, tr.sols, hubs)
    res = cluster(holders, edges, hubs)
    farmed = holders[: len(funders) * 3]
    want = {w: f for i, f in enumerate(funders) for w in farmed[i * 3 : i * 3 + 3]}
    hit = sum(res.cluster_of[w] == res.cluster_of[f] for w, f in want.items())
    cex_hit = sum(res.cluster_of[w] != w for w in cex)
    recall = Fraction(hit, len(want))
    return Outcome(
        recall >= Fraction(95, 100),
        f"self={float(recall):.0%} ({hit}/{len(want)}); cex={cex_hit}/{len(cex)} (hub residual)",
    )


def row_retroactive_merge(rng: random.Random) -> Outcome:
    """Retroactive merge: past epochs are untouched; the current epoch equals a
    from-genesis rebuild under the new cluster map."""
    a, b = _w(rng, "retro-a"), _w(rng, "retro-b")
    amt = rng.randint(1_000, 10**5) * TOK
    tr = Trades("retro")
    tr.buy(a, amt, T0 - 20 * DAY)
    tr.buy(b, amt, T0 - 20 * DAY)
    r0, s0 = run_epoch(tr.inputs(T0), acc.PARAMS, empty_state())
    published = (r0.inputs_hash, dict(r0.payouts))
    r1, _ = run_epoch(tr.inputs(T0 + DAY), acc.PARAMS, s0)  # the merge is not known yet
    late = replace(tr.inputs(T0 + DAY), overrides=((a, b, "review-1"),))
    merged, _ = run_epoch(late, acc.PARAMS, s0)
    fresh, _ = run_epoch(late, acc.PARAMS, empty_state())  # from-genesis rebuild, no scores
    key = [(s.cluster, s.twab, s.score) for s in merged.scores]
    ok = published == (r0.inputs_hash, dict(r0.payouts))
    ok = ok and len(_clusters(r1)) == 2 and len(_clusters(merged)) == 1
    ok = ok and key == [(s.cluster, s.twab, s.score) for s in fresh.scores]
    return Outcome(ok, f"past hash unchanged; 2→1 cluster; scores == fresh rebuild={ok}")


ROWS = (
    ("Buy and sell in the same second", "intra-second states zero; p(t) end-of-second",
     row_same_second),
    ("Pool depth below the trust threshold", "boost off, unlock paused, base rewards unchanged",
     row_trust_threshold),
    ("Missing / decreasing block time, skipped slots", "same output as the clean log",
     row_clock_clamp),
    ("Same fee-paying app + one-sided signals", "no merge; payer in the review list",
     row_shared_payer),
    ("Single commercial transfer", "no merge", row_single_transfer),
    ("False merge of two independent clusters", "tokens' score same; cap damage reported",
     row_false_merge),
    ("Sybil recall (self-funded / CEX-funded)", "self ≥ 95%; CEX reported as residual",
     row_sybil_recall),
    ("Retroactive merge", "past epochs unchanged; equals a from-genesis rebuild",
     row_retroactive_merge),
    *ARB_ROWS,
)  # fmt: skip
