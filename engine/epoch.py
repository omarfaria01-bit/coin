"""Epoch orchestrator (ENGINE_DESIGN §8). Pure glue; no I/O, no wall clock."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from engine.eligibility import is_eligible
from engine.ledger import ledger_segments
from engine.merkle import claims_document
from engine.params import CoinParams
from engine.rewards import (
    DEFAULT_G,
    capped_shares_v033,
    epoch_budget,
    exact_payout,
    split_cluster_payout,
)
from engine.scoring import score_lot
from engine.sybil import build_evidence, cluster
from engine.twab import twab
from engine.types import (
    ClusterId,
    EventKind,
    FirstFunding,
    PricePoint,
    SolTransfer,
    TokenEvent,
    WalletId,
)
from engine.vesting import breaches_soft_lock, locked_amount, unlocked_fraction


@dataclass(frozen=True, slots=True)
class VestingEntry:
    """Soft-mode vested wallet; p_entry is D13 units."""

    wallet: WalletId
    vested_amount: int
    p_entry: float
    t0: int


@dataclass(frozen=True, slots=True)
class EpochState:
    """Carried between epochs (epoch 0 is empty, pot 0)."""

    epoch: int
    pot: int
    carry: Mapping[WalletId, int]
    forfeit_until: Mapping[ClusterId, int]
    unlocked: Mapping[WalletId, float]
    vesting: tuple[VestingEntry, ...]


@dataclass(frozen=True, slots=True)
class EpochInputs:
    t0: int
    t1: int
    slot_range: tuple[int, int]
    events: tuple[TokenEvent, ...]
    sol_transfers: tuple[SolTransfer, ...]
    fundings: tuple[FirstFunding, ...]
    prices: tuple[PricePoint, ...]
    decimals: int
    sol_usd: float  # display-only leftover; not used for eligibility (v0.3.3 §2)
    pot_inflow: int
    excluded: frozenset[WalletId]
    hubs: frozenset[WalletId]
    total_supply: int  # token base units, > 0 (v0.3.3 §2 eligibility floor)

    def __post_init__(self) -> None:
        if isinstance(self.total_supply, bool) or not isinstance(self.total_supply, int):
            raise TypeError("total_supply must be an int (token base units)")
        if self.total_supply <= 0:
            raise ValueError(f"total_supply must be > 0, got {self.total_supply}")


@dataclass(frozen=True, slots=True)
class ClusterScore:
    cluster: ClusterId
    twab: float
    hold: float
    churn: float
    boost: float
    score: float
    share: float


@dataclass(frozen=True, slots=True)
class EpochResult:
    epoch: int
    payouts: Mapping[WalletId, int]
    scores: tuple[ClusterScore, ...]
    rollover: int
    dust: int
    pot: int
    rail: Literal["push", "merkle", "none"]
    claims: dict[str, Any] | None
    push: tuple[tuple[WalletId, int], ...]
    review: tuple[ClusterId, ...]
    inputs_hash: str
    transferred_or_claimable: Mapping[WalletId, int]


def empty_state() -> EpochState:
    return EpochState(0, 0, {}, {}, {}, ())


def _d13(price_sol_per_whole: float, decimals: int) -> float:
    return price_sol_per_whole * 1e9 / (10**decimals)


def _twap(prices: Sequence[PricePoint], a: int, b: int, decimals: int) -> float:
    """§8 step 1: time-weighted mid of the 1-min series on [a, b), in D13 units."""
    if b <= a:
        raise ValueError(f"twap window must be positive, got a={a} b={b}")
    if not prices:
        raise ValueError("twap: window has no price")
    ordered = sorted(prices, key=lambda p: p.ts)
    price = ordered[0].price
    has = False
    cursor = a
    start = a
    numer = 0.0
    for pt in ordered:
        if pt.ts <= a:
            price = pt.price
            has = True
            continue
        if pt.ts >= b:
            break
        if not has:
            price = pt.price
            cursor = pt.ts
            start = pt.ts
            has = True
            continue
        if pt.ts > cursor:
            numer += price * (pt.ts - cursor)
            cursor = pt.ts
        price = pt.price
        has = True
    if not has:
        raise ValueError("twap: window has no price")
    numer += price * (b - cursor)
    if b <= start:
        raise ValueError(f"twap: empty span, start={start} b={b}")
    return _d13(numer / (b - start), decimals)


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


def _balance_at(path: Sequence[tuple[int, int]], ts: int) -> int:
    bal = 0
    for t, new in path:
        if t > ts:
            break
        bal = new
    return bal


def _held_in_window(path: Sequence[tuple[int, int]], t0: int, t1: int) -> bool:
    if _balance_at(path, t0 - 1) > 0:
        return True
    return any(t0 <= t < t1 and bal > 0 for t, bal in path)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _inputs_hash(inp: EpochInputs, params: CoinParams) -> str:
    # §8 step 11: slot_range + params + counts + sha256 of events sorted by (slot, sig, ix).
    evs = sorted(inp.events, key=lambda e: (e.slot, e.sig, e.ix))
    ev_rows = [
        [e.slot, e.ts, e.sig, e.ix, str(e.kind), e.src, e.dst, e.amount, e.lamports, e.fee_payer]
        for e in evs
    ]
    payload = {
        "slot_range": list(inp.slot_range),
        "params": params.model_dump(mode="json"),
        "counts": {
            "events": len(inp.events),
            "sol_transfers": len(inp.sol_transfers),
            "fundings": len(inp.fundings),
            "prices": len(inp.prices),
        },
        "events_sha256": hashlib.sha256(_canon(ev_rows).encode()).hexdigest(),
    }
    return hashlib.sha256(_canon(payload).encode()).hexdigest()


def run_epoch(
    inp: EpochInputs, params: CoinParams, prev: EpochState
) -> tuple[EpochResult, EpochState]:
    expected = params.epoch.hours * 3600
    if inp.t1 - inp.t0 != expected:
        raise ValueError(f"t1-t0 must equal epoch.hours*3600, got {inp.t1 - inp.t0} vs {expected}")
    if inp.pot_inflow < 0 or prev.pot < 0:
        raise ValueError("pot and pot_inflow must be >= 0")

    def twap(a: int, b: int) -> float:
        return _twap(inp.prices, a, b, inp.decimals)

    events = tuple(e for e in inp.events if e.ts <= inp.t1)
    # §8 step 3 (holders: anyone with a balance during the epoch)
    holders: set[WalletId] = set()
    touched: set[WalletId] = set()
    for ev in events:
        if ev.src:
            touched.add(ev.src)
        if ev.dst:
            touched.add(ev.dst)
    paths = {w: _changes(events, w) for w in touched}
    for w, path in paths.items():
        if w not in inp.excluded and _held_in_window(path, inp.t0, inp.t1):
            holders.add(w)
    holder_list = sorted(holders)
    bals = {w: _balance_at(paths.get(w, ()), inp.t1) for w in holder_list}
    evidence = build_evidence(
        holder_list, events, inp.sol_transfers, inp.fundings, bals, inp.hubs, params.sybil
    )
    clustered = cluster(holder_list, evidence, params.sybil)
    # §8 step 4
    twab_w = {w: twab(0, paths.get(w, ()), inp.t0, inp.t1) for w in holder_list}
    twab_c = {cid: sum(twab_w[w] for w in members) for cid, members in clustered.members.items()}
    # §8 step 5 — price-free supply-share eligibility (COIN_MATH v0.3.3 §2)
    eligible: set[ClusterId] = set()
    for cid in clustered.members:
        if (
            is_eligible(twab_c[cid], inp.total_supply, params.eligibility.min_eligible_share)
            and prev.forfeit_until.get(cid, 0) <= inp.t1
        ):
            eligible.add(cid)
    # §8 step 6 — v0.3.3 §3–§6: score = Σ over lots of (E1 + u·E2), u = 1 (boost off at
    # launch, §16). Lots come from the v0.3.3 ledger under this epoch's cluster map, as a
    # step function of the second, so lots sold mid-epoch still count for the time held.
    hold = params.hold
    knots = hold.knot_fractions()
    epoch_len = inp.t1 - inp.t0
    segments = ledger_segments(
        events, inp.excluded, inp.t0, inp.t1, cluster_of=clustered.cluster_of
    )
    s_w: dict[WalletId, Fraction] = {}
    for w in holder_list:
        total = Fraction(0)
        for a, b, lots in segments.get(w, ()):
            for lot in lots:
                part = score_lot(
                    lot.amount,
                    lot.t_acquired,
                    a,
                    b,
                    tainted_until=lot.tainted_until,
                    knots=knots,
                    t_start_seconds=hold.t_start_seconds,
                    boost_age_seconds=hold.boost_age_seconds,
                )
                total += part * Fraction(b - a, epoch_len)
        s_w[w] = total
    rows: dict[ClusterId, ClusterScore] = {}
    raw_scores: dict[ClusterId, Fraction] = {}
    for cid, members in clustered.members.items():
        s_c = sum((s_w.get(w, Fraction(0)) for w in members), Fraction(0))
        eff_h = float(s_c / Fraction(twab_c[cid])) if twab_c[cid] > 0 else 0.0
        s_c = s_c if cid in eligible else Fraction(0)
        raw_scores[cid] = s_c
        # hold = effective multiplier s_c / B̄_c; churn and boost are gone in v0.3.3 (1.0).
        rows[cid] = ClusterScore(cid, twab_c[cid], eff_h, 1.0, 1.0, float(s_c), 0.0)
    # §8 step 7 — soft vesting (D10); TWAP window from params (D14)
    unlocked = dict(prev.unlocked)
    forfeit_until = dict(prev.forfeit_until)
    forfeited: set[ClusterId] = set()
    unlock_s = int(params.vesting.unlock_twap_hours * 3600)
    forfeit_s = int(params.vesting.forfeit_days * 86_400)
    outflows = [
        ev
        for ev in sorted(events, key=lambda e: (e.slot, e.sig, e.ix))
        if inp.t0 <= ev.ts < inp.t1
        and ev.kind in (EventKind.SELL, EventKind.TRANSFER)
        and ev.src is not None
    ]
    for entry in prev.vesting:
        path = paths.get(entry.wallet, _changes(events, entry.wallet))
        for ev in outflows:
            if ev.src != entry.wallet:
                continue
            prev_u = unlocked.get(entry.wallet, 0.0)
            unlocked[entry.wallet] = unlocked_fraction(
                prev_u,
                ev.ts,
                entry.t0,
                twap(ev.ts - unlock_s, ev.ts),
                entry.p_entry,
                params.vesting,
            )
            locked = locked_amount(entry.vested_amount, unlocked[entry.wallet])
            # Balance after this outflow: path entry at ev.ts (already applied).
            after = _balance_at(path, ev.ts)
            if breaches_soft_lock(after, locked):
                cid = clustered.cluster_of.get(entry.wallet, entry.wallet)
                forfeit_until[cid] = ev.ts + forfeit_s
                forfeited.add(cid)
        unlocked[entry.wallet] = unlocked_fraction(
            unlocked.get(entry.wallet, 0.0),
            inp.t1,
            entry.t0,
            twap(inp.t1 - unlock_s, inp.t1),
            entry.p_entry,
            params.vesting,
        )
    for cid in forfeited:
        raw_scores[cid] = Fraction(0)
        row = rows[cid]
        rows[cid] = ClusterScore(cid, row.twab, row.hold, row.churn, row.boost, 0.0, 0.0)
    # §8 step 8
    pot = prev.pot + inp.pot_inflow
    budget = epoch_budget(pot, params.rewards.alpha_per_day, params.epoch.hours)
    skip = (not params.rewards.enabled) or budget < params.rewards.min_epoch_payout_lamports
    payouts: dict[WalletId, int] = {}
    rollover = 0
    dust = 0
    shares: dict[ClusterId, Fraction] = {cid: Fraction(0) for cid in rows}
    if not skip:
        # §8 step 9 — v0.3.3 §6: cap with uplift limit G, exact integer payout, exact split.
        cap = Fraction(str(params.scoring.cap))
        shares = capped_shares_v033(raw_scores, cap, DEFAULT_G)
        exact = exact_payout(budget, shares)
        rollover = exact.rollover_units
        for cid, amt in exact.payouts.items():
            members = clustered.members.get(cid, (cid,))
            parts = split_cluster_payout(amt, {w: s_w.get(w, Fraction(0)) for w in members})
            for w, pay in parts.items():
                if pay:
                    payouts[w] = payouts.get(w, 0) + pay
    paid = sum(payouts.values())
    pot_next = pot if skip else pot - paid
    for cid, row in rows.items():
        rows[cid] = ClusterScore(
            cid, row.twab, row.hold, row.churn, row.boost, row.score, float(shares.get(cid, 0))
        )
    # §8 step 10
    prev_carry = {w: int(v) for w, v in prev.carry.items() if int(v)}
    due: dict[WalletId, int] = dict(prev_carry)
    for w, amt in payouts.items():
        due[w] = due.get(w, 0) + amt
    due = {w: amt for w, amt in due.items() if amt > 0}
    n_eligible = len(eligible - forfeited)
    transferred: dict[WalletId, int] = {}
    next_carry: dict[WalletId, int] = {}
    claims: dict[str, Any] | None = None
    push: tuple[tuple[WalletId, int], ...] = ()
    rail: Literal["push", "merkle", "none"] = "none"
    if skip or not due:
        next_carry = dict(sorted((due or prev_carry).items()))
        transferred = {}
        rail = "none"
    elif n_eligible < params.rewards.push_max_eligible:
        rail = "push"
        min_x = params.rewards.push_min_transfer_lamports
        paid_now: list[tuple[WalletId, int]] = []
        for w in sorted(due):
            if due[w] >= min_x:
                paid_now.append((w, due[w]))
                transferred[w] = due[w]
            else:
                next_carry[w] = due[w]
        push = tuple(paid_now)
    else:
        rail = "merkle"
        transferred = dict(sorted(due.items()))
        claims = claims_document(transferred, version=prev.epoch)
        next_carry = {}
    # Conservation (§8)
    lhs = prev.pot + inp.pot_inflow + sum(prev_carry.values())
    rhs = pot_next + sum(transferred.values()) + sum(next_carry.values())
    if lhs != rhs:
        raise ValueError(f"conservation failed: {lhs} != {rhs}")
    result = EpochResult(
        epoch=prev.epoch,
        payouts=dict(sorted(payouts.items())),
        scores=tuple(rows[cid] for cid in sorted(rows)),
        rollover=rollover,
        dust=dust,
        pot=pot_next,
        rail=rail,
        claims=claims,
        push=push,
        review=clustered.review,
        inputs_hash=_inputs_hash(inp, params),
        transferred_or_claimable=dict(sorted(transferred.items())),
    )
    nxt = EpochState(
        epoch=prev.epoch + 1,
        pot=pot_next,
        carry=dict(sorted(next_carry.items())),
        forfeit_until=dict(sorted(forfeit_until.items())),
        unlocked=dict(sorted(unlocked.items())),
        vesting=prev.vesting,
    )
    return result, nxt
