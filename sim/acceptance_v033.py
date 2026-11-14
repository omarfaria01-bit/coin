"""COIN_MATH v0.3.3 §14 acceptance rows on the real engine (#84 step 1: score, eligibility,
cap, pending, split). Every row drives `engine.epoch.run_epoch` (or the exact engine
function it calls) on seeded random trades; a row passes only if it passes on every seed.

    uv run python -m sim.run --acceptance --seeds 20   # exits 1 on any failing row
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256

from engine.epoch import EpochInputs, EpochResult, EpochState, empty_state, run_epoch
from engine.params import CoinParams
from engine.rewards import epoch_budget_v033
from engine.scoring import h_of_age
from engine.types import EventKind, SolTransfer, TokenEvent
from sim.agents import wallet_id

DAY, HOUR = 86_400, 3_600
T0, T1 = 0, DAY
SUPPLY = 10**18  # 1e9 tokens, 9 decimals → eligibility floor 1e12 base units (1/1e6)
TOK = 10**9
PARAMS = CoinParams()
ALPHA = Fraction(str(PARAMS.rewards.alpha_per_day))
MIN_Q = PARAMS.rewards.push_min_transfer_lamports


@dataclass(frozen=True)
class Outcome:
    passed: bool
    evidence: str


class Trades:
    """Synthetic event log: unique sigs, slot = ts + offset, price 1e-6 Q per base unit."""

    def __init__(self, tag: str) -> None:
        self.tag, self.events, self.sols, self._n = tag, [], [], 0

    def _sig(self) -> str:
        self._n += 1
        return sha256(f"{self.tag}:{self._n}".encode()).hexdigest()

    def buy(self, w: str, amount: int, ts: int) -> None:
        self.events.append(TokenEvent(ts + 10**7, ts, self._sig(), 0, EventKind.BUY, None, w,
                                      amount, max(1, amount // 10**6), w))  # fmt: skip

    def sell(self, w: str, amount: int, ts: int) -> None:
        self.events.append(TokenEvent(ts + 10**7, ts, self._sig(), 0, EventKind.SELL, w, None,
                                      amount, max(1, amount // 10**6), w))  # fmt: skip

    def send(self, a: str, b: str, amount: int, ts: int) -> None:
        self.events.append(TokenEvent(ts + 10**7, ts, self._sig(), 0, EventKind.TRANSFER, a, b,
                                      amount, None, a))  # fmt: skip

    def fund(self, a: str, b: str, lamports: int, ts: int) -> None:
        self.sols.append(SolTransfer(ts + 10**7, ts, self._sig(), a, b, lamports))

    def inputs(self, t0: int = T0, inflow: int = 10**12) -> EpochInputs:
        return EpochInputs(
            t0=t0, t1=t0 + DAY, slot_range=(t0 + 10**7, t0 + DAY + 10**7),
            events=tuple(self.events), sol_transfers=tuple(self.sols), fundings=(),
            prices=(), decimals=9, sol_usd=100.0, pot_inflow=inflow, excluded=frozenset(),
            hubs=frozenset(), total_supply=SUPPLY,
        )  # fmt: skip


def _run(tr: Trades, t0: int = T0, inflow: int = 10**12, prev: EpochState | None = None,
         params: CoinParams = PARAMS) -> tuple[EpochResult, EpochState]:  # fmt: skip
    return run_epoch(tr.inputs(t0, inflow), params, prev or empty_state())


def _score(result: EpochResult, w: str) -> Fraction:
    return next((Fraction(r.score) for r in result.scores if r.cluster == w), Fraction(0))


_REL = Fraction(1, 10**12)  # ClusterScore.score is a float report of the exact Fraction


def _same(a: Fraction, b: Fraction) -> bool:
    return abs(a - b) <= _REL * max(abs(a), abs(b))


def _w(rng: random.Random, label: str) -> str:
    return wallet_id(f"acc-{label}-{rng.random()}")


# ---------------------------------------------------------------- rows


def row_hold_time(rng: random.Random) -> Outcome:
    """7d < 30d < 60d < 90d strictly, flat after 90d (same balance, one epoch)."""
    amt = rng.randint(1_000, 10**6) * TOK
    ages = (7, 30, 60, 90, 120)
    scores = []
    for d in ages:
        tr, w = Trades(f"hold{d}"), _w(rng, f"h{d}")
        tr.buy(w, amt, T0 - d * DAY)
        scores.append(_score(_run(tr)[0], w))
    ok = (
        all(a < b for a, b in zip(scores[:4], scores[1:4], strict=False)) and scores[3] == scores[4]
    )
    return Outcome(ok, "h=" + ",".join(f"{float(s / amt):.3f}" for s in scores))


def row_scalper(rng: random.Random) -> Outcome:
    """Churning so no lot reaches 2h: score 0."""
    tr, w = Trades("scalp"), _w(rng, "scalp")
    amt, ts = rng.randint(1_000, 10**5) * TOK, T0
    while ts < T1 - 2 * HOUR:
        tr.buy(w, amt, ts)
        hold = rng.randint(60, 2 * HOUR - 1)
        tr.sell(w, amt, ts + hold)
        ts += hold + rng.randint(1, 600)
    s = _score(_run(tr)[0], w)
    return Outcome(s == 0, f"score={float(s)} trips={len(tr.events) // 2}")


def row_sniper(rng: random.Random) -> Outcome:
    """Buys shortly before the epoch ends: score 0 for 2h."""
    tr, w = Trades("snipe"), _w(rng, "snipe")
    tr.buy(w, rng.randint(1_000, 10**6) * TOK, T1 - rng.randint(1, 2 * HOUR - 1))  # strictly < 2h
    s = _score(_run(tr)[0], w)
    return Outcome(s == 0, f"score={float(s)}")


def row_partial_sale(rng: random.Random) -> Outcome:
    """Score lost == score of the lots sold (newest first); old lots untouched."""
    old, new = rng.randint(1_000, 10**5) * TOK, rng.randint(1_000, 10**5) * TOK
    sold = rng.randint(1, new // TOK) * TOK
    a, b = Trades("ps-a"), Trades("ps-b")
    wa = wb = _w(rng, "ps")
    for tr in (a, b):
        tr.buy(wa, old, T0 - 30 * DAY)
        tr.buy(wa, new, T0 - 3 * DAY)
    b.sell(wb, sold, T0 - DAY)
    c = Trades("ps-c")  # the reference: only what is left
    c.buy(wa, old, T0 - 30 * DAY)
    c.buy(wa, new - sold, T0 - 3 * DAY)
    sb, sc = _score(_run(b)[0], wb), _score(_run(c)[0], wa)
    return Outcome(_same(sb, sc), f"after_sale={float(sb):.0f} expected={float(sc):.0f}")


def row_new_buy_on_old_bag(rng: random.Random) -> Outcome:
    """A new buy leaves the old lots' score unchanged (new lot < 2h adds 0)."""
    w, amt = _w(rng, "nb"), rng.randint(1_000, 10**5) * TOK
    a, b = Trades("nb-a"), Trades("nb-b")
    for tr in (a, b):
        tr.buy(w, amt, T0 - 40 * DAY)
    b.buy(w, rng.randint(1, 10**6) * TOK, T1 - rng.randint(1, 2 * HOUR - 1))
    sa, sb = _score(_run(a)[0], w), _score(_run(b)[0], w)
    return Outcome(_same(sa, sb), f"before={float(sa):.0f} after={float(sb):.0f}")


def row_transfer_age_reset(rng: random.Random) -> Outcome:
    """Receiver starts at age 0: nothing moved scores before 2h, never the sender's age."""
    tr, a, b = Trades("tx"), _w(rng, "tx-a"), _w(rng, "tx-b")
    amt = rng.randint(1_000, 10**5) * TOK
    tr.buy(a, amt, T0 - 90 * DAY)
    t = T0 + rng.randint(0, DAY - 1)
    tr.send(a, b, amt, t)
    held = T1 - t
    s, cap = _score(_run(tr)[0], b), h_of_age(held) * amt * held / DAY
    return Outcome(
        s <= cap and (held >= 2 * HOUR or s == 0), f"recv={float(s):.0f} bound={float(cap):.0f}"
    )


def row_cap(rng: random.Random) -> Outcome:
    """10 clusters (one whale): none above 5%, none above 2× proportional, rest stays."""
    tr, ws = Trades("cap"), [_w(rng, f"cap{i}") for i in range(10)]
    for i, w in enumerate(ws):
        tr.buy(
            w,
            (10**7 if i == 0 else rng.randint(1_000, 10**5)) * TOK,
            T0 - 10 * DAY,
        )
    res, _ = _run(tr)
    total = sum(Fraction(r.score) for r in res.scores)
    shares = {r.cluster: Fraction(r.share) for r in res.scores}
    over = [w for w, s in shares.items() if s > Fraction(1, 20) + Fraction(1, 10**9)]
    uplift = [w for w in ws if shares[w] > 2 * _score(res, w) / total + Fraction(1, 10**9)]
    paid = sum(res.payouts.values())
    budget = epoch_budget_v033(10**12, ALPHA)
    evidence = f"max_pi={float(max(shares.values())):.4f} paid/R={paid / budget:.3f}"
    return Outcome(not over and not uplift and paid < budget, evidence)


def row_zero_score(rng: random.Random) -> Outcome:
    """S = 0: nothing distributed, pot unchanged, no error."""
    tr = Trades("s0")
    tr.buy(_w(rng, "s0"), rng.randint(1_000, 10**5) * TOK, T1 - HOUR)  # only < T_START lots
    inflow = rng.randint(10**8, 10**12)
    res, nxt = _run(tr, inflow=inflow)
    return Outcome(not res.payouts and nxt.pot == inflow, f"pot={nxt.pot} paid={res.payouts}")


def row_exact_payout(rng: random.Random) -> Outcome:
    """Σ payouts + rollover_units == R_e, in Q base units."""
    tr = Trades("ex")
    for i in range(rng.randint(1, 40)):
        tr.buy(_w(rng, f"ex{i}"), rng.randint(1_000, 10**7) * TOK, T0 - rng.randint(0, 100 * DAY))
    inflow = rng.randint(10**7, 10**13)
    res, _ = _run(tr, inflow=inflow)
    r_e = epoch_budget_v033(inflow, ALPHA)
    got = sum(res.payouts.values()) + res.rollover
    return Outcome(got == r_e, f"sum+rollover={got} R_e={r_e}")


def row_multiplier_bounds(rng: random.Random) -> Outcome:
    """Under 2h scores 0; never above 2.8× without boost."""
    ages = [rng.randint(0, 2 * HOUR - 1), *(rng.randint(0, 400 * DAY) for _ in range(20))]
    hs = [h_of_age(a) for a in ages]
    ok = hs[0] == 0 and all(Fraction(0) <= h <= Fraction(14, 5) for h in hs)
    return Outcome(ok, f"h(<2h)={hs[0]} max_h={float(max(hs)):.3f}")


def row_pending(rng: random.Random) -> Outcome:
    """Below MIN_PAYOUT_Q stays pending, never decreases, paid once the threshold is passed."""
    tr, w, big = Trades("pend"), _w(rng, "pend"), _w(rng, "pend-big")
    tr.buy(w, rng.randint(1_000, 3_000) * TOK, T0 - 10 * DAY)
    tr.buy(big, 10**6 * TOK, T0 - 10 * DAY)
    prev, seen, paid_at, ok_paid = empty_state(), [], None, False
    for e in range(60):
        res, prev = _run(tr, t0=e * DAY, inflow=10**8, prev=prev)
        if w in res.transferred_or_claimable:
            paid_at = e
            ok_paid = res.transferred_or_claimable[w] >= MIN_Q and prev.carry.get(w, 0) == 0
            break
        seen.append(prev.carry.get(w, 0))
    mono = all(a <= b for a, b in zip(seen, seen[1:], strict=False))
    ok = mono and paid_at is not None and ok_paid and all(p < MIN_Q for p in seen)
    return Outcome(ok, f"pending_epochs={len(seen)} paid_at_epoch={paid_at}")


def row_split_never_gains(rng: random.Random) -> Outcome:
    """Same trades split across 2–10 unlinked wallets (boost off): total score never higher."""
    n = rng.randint(2, 10)
    one, many = Trades("sp1"), Trades("spn")
    w1, ws = _w(rng, "sp-one"), [_w(rng, f"sp{i}") for i in range(n)]
    for _ in range(rng.randint(1, 15)):
        amt, ts = rng.randint(1, 10**5) * TOK, T0 - rng.randint(0, 60 * DAY)
        one.buy(w1, amt, ts)
        many.buy(rng.choice(ws), amt, ts)
    s1 = _score(_run(one)[0], w1)
    res_many, _ = _run(many)
    sn = sum(_score(res_many, w) for w in ws)
    return Outcome(sn <= s1 or _same(sn, s1), f"n={n} split={float(sn):.0f} single={float(s1):.0f}")


def row_small_holder(rng: random.Random) -> Outcome:
    """€100 at market caps $50k..$50M: eligible every time (supply share ≥ 1/1e6 up to $100M)."""
    eur_usd, out = 1.08, []
    for mcap in (5 * 10**4, 5 * 10**5, 5 * 10**6, 5 * 10**7):
        tokens = SUPPLY * Fraction(100) * Fraction(str(eur_usd)) / mcap
        tr, w = Trades(f"sm{mcap}"), _w(rng, f"sm{mcap}")
        tr.buy(w, int(tokens), T0 - 3 * DAY)
        res, _ = _run(tr, inflow=10**10)
        out.append((mcap, _score(res, w) > 0))
    return Outcome(
        all(ok for _, ok in out), " ".join(f"${m:,}:{'ok' if ok else 'NO'}" for m, ok in out)
    )


ROWS: tuple[tuple[str, str, Callable[[random.Random], Outcome]], ...] = (
    ("Holding time 7d/30d/60d/90d", "strictly increasing, flat after 90d", row_hold_time),
    ("Scalper churning < 2h", "score = 0", row_scalper),
    ("Snapshot sniper", "score = 0 for 2h", row_sniper),
    ("Partial sale", "loses exactly the sold lots' score (newest first)", row_partial_sale),
    ("New buy on an old bag", "old lots' score unchanged", row_new_buy_on_old_bag),
    ("Transfer to another owner", "receiver starts at age 0", row_transfer_age_reset),
    ("Whale cap, 10 clusters", "π ≤ 5%, ≤ 2× proportional, rest in pot", row_cap),
    ("S = 0", "nothing paid, pot unchanged", row_zero_score),
    ("Exact payout", "Σ payouts + rollover == R_e", row_exact_payout),
    ("Multiplier bounds", "< 2h → 0, ≤ 2.8× without boost", row_multiplier_bounds),
    ("Small balance below MIN_PAYOUT_Q", "pending never decreases, paid at threshold", row_pending),
    ("Any split, 2–10 wallets, boost off", "total score never higher", row_split_never_gains),
    ("€100 holder at $50k..$50M", "eligible in every case", row_small_holder),
)


@dataclass(frozen=True)
class RowResult:
    name: str
    condition: str
    passed: int
    seeds: int
    worst: str  # first failing seed's evidence, else seed 0's


def all_rows() -> tuple[tuple[str, str, Callable[[random.Random], Outcome]], ...]:
    """Score/payout rows here, then the attack rows (sim.acceptance_attacks_v033, #84 step 2)."""
    from sim.acceptance_attacks_v033 import ROWS as ATTACK_ROWS  # imports this module

    return (*ROWS, *ATTACK_ROWS)


def run_rows(seeds: int) -> list[RowResult]:
    out = []
    for name, cond, fn in all_rows():
        results = [(s, fn(random.Random(f"{name}:{s}"))) for s in range(seeds)]
        fails = [(s, o) for s, o in results if not o.passed]
        s, o = fails[0] if fails else results[0]
        out.append(RowResult(name, cond, seeds - len(fails), seeds, f"seed {s}: {o.evidence}"))
    return out


def render(rows: list[RowResult]) -> str:
    lines = ["| §14 row | pass condition | result | evidence (worst seed) |", "|---|---|---|---|"]
    for r in rows:
        verdict = "PASS" if r.passed == r.seeds else f"FAIL ({r.seeds - r.passed}/{r.seeds} seeds)"
        lines.append(f"| {r.name} | {r.condition} | {verdict} | {r.worst} |")
    return "\n".join(lines) + "\n"
