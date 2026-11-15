"""Epoch orchestrator (ENGINE_DESIGN §8). Pure glue; no I/O, no wall clock."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from engine.balances import WalletBalance, apply_push, credit_many, open_claims
from engine.eligibility import is_eligible
from engine.ledger import ledger_segments
from engine.merkle import claims_document
from engine.params import CoinParams
from engine.prices import HarmonicOracle, ReservePoint
from engine.rewards import (
    DEFAULT_G,
    capped_shares_v033,
    epoch_budget_v033,
    exact_payout,
    split_cluster_payout,
)
from engine.scoring import score_lot
from engine.sybil_v033 import (
    cluster,
    l4_co_trades,
    l5_identical_balances,
    l6_shared_proceeds,
    s1_cosigned,
    s2_funded_buys,
    s3_overrides,
    transfer_links,
)
from engine.twab import twab_exact
from engine.types import (
    ClusterId,
    EventKind,
    FirstFunding,
    PricePoint,
    SolTransfer,
    TokenEvent,
    WalletId,
)
from engine.vesting import VestedLot, soft_vesting_breaches


@dataclass(frozen=True, slots=True)
class VestingEntry:
    """Soft-mode vested lot. ``p_entry``: Q base units per token base unit (the unit of
    ``engine.prices.price_at``), exact; ints, "num/den" strings and floats (by their repr)
    are normalized to a Fraction."""

    wallet: WalletId
    vested_amount: int
    p_entry: Fraction
    t0: int

    def __post_init__(self) -> None:
        value = self.p_entry
        if isinstance(value, bool) or not isinstance(value, Fraction | int | str | float):
            raise TypeError("p_entry must be a Fraction, int, 'num/den' string or float")
        object.__setattr__(self, "p_entry", Fraction(str(value)))


@dataclass(frozen=True, slots=True)
class EpochState:
    """Carried between epochs (epoch 0 is empty, pot 0).

    The §13 running balance per wallet is (``carry``, ``paid_total``): ``carry`` is
    ``pending`` (earned, not yet paid; never expires) and ``earned_total`` is
    ``paid_total + pending`` (see ``balances``).
    """

    epoch: int
    pot: int
    carry: Mapping[WalletId, int]
    forfeit_until: Mapping[ClusterId, int]
    unlocked: Mapping[WalletId, float]
    vesting: tuple[VestingEntry, ...]
    paid_total: Mapping[WalletId, int] = field(default_factory=dict)

    @property
    def balances(self) -> dict[WalletId, WalletBalance]:
        """§13 book: every wallet that ever earned, sorted by wallet id."""
        wallets = sorted(set(self.carry) | set(self.paid_total))
        return {
            w: WalletBalance(
                w, self.paid_total.get(w, 0) + self.carry.get(w, 0), self.paid_total.get(w, 0)
            )
            for w in wallets
        }


@dataclass(frozen=True, slots=True)
class EpochInputs:
    t0: int
    t1: int
    slot_range: tuple[int, int]
    events: tuple[TokenEvent, ...]
    sol_transfers: tuple[SolTransfer, ...]
    fundings: tuple[FirstFunding, ...]
    # v0.2 swap-print prices: not read by run_epoch (eligibility and score read no price;
    # the §11 price unlock reads `reserves`). Kept until the adapters drop them.
    prices: tuple[PricePoint, ...]
    decimals: int
    sol_usd: float  # display-only leftover; not used for eligibility (v0.3.3 §2)
    pot_inflow: int
    excluded: frozenset[WalletId]
    hubs: frozenset[WalletId]
    total_supply: int  # token base units, > 0 (v0.3.3 §2 eligibility floor)
    # v0.3.3 §7 S1: tx signature → signer set (from the parser); S3: logged manual merges.
    signers: Mapping[str, frozenset[WalletId]] = field(default_factory=dict)
    overrides: tuple[tuple[WalletId, WalletId, str], ...] = ()
    # §0 pool reserves (price + trusted seconds) for the §11 price unlock; () = none known.
    # Points after t1 are harmless: unlock queries stop at t1 (the CLI drops them anyway).
    reserves: tuple[ReservePoint, ...] = ()

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
    if params.underwater.enabled:
        # §16: the boost is off at launch; wiring u_lot (§5) needs trusted pool reserves.
        raise ValueError("underwater.enabled: the §5 boost is not wired into run_epoch yet")
    if params.epoch.hours != 24:
        raise ValueError("v0.3.3 §0: epochs are 86,400 s (epoch.hours must be 24)")
    expected = params.epoch.hours * 3600
    if inp.t1 - inp.t0 != expected:
        raise ValueError(f"t1-t0 must equal epoch.hours*3600, got {inp.t1 - inp.t0} vs {expected}")
    if inp.pot_inflow < 0 or prev.pot < 0:
        raise ValueError("pot and pot_inflow must be >= 0")

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
    # v0.3.3 §7: strong evidence (S1–S3) or links Σ ≥ 1 with an L1/L2; hubs ignored.
    hubs, sols = inp.hubs, inp.sol_transfers
    created = {f.wallet: f.created_ts for f in inp.fundings}
    edges = [
        *s1_cosigned(frozenset(holder_list), inp.signers, hubs),
        *s2_funded_buys(events, sols, hubs),
        *s3_overrides(inp.overrides),
        *transfer_links(events, sols, hubs),
        *l4_co_trades(events, hubs),
        *l5_identical_balances(bals, created, hubs),
        *l6_shared_proceeds(events, sols, hubs),
    ]
    clustered = cluster(holder_list, edges, hubs, events)
    # §8 step 7 (moved before scoring, §1 order: clusters → ledger → score) — v0.3.3 §11 B.
    # Replayed over the full history under this cluster map. u_price reads P̃_h from pool
    # reserves and is skipped for any minute whose 24h window is not fully trusted (§0).
    kept = [e for e in prev.vesting if e.vested_amount > 0 and e.p_entry > 0]
    vested = [
        VestedLot(
            clustered.cluster_of.get(e.wallet, e.wallet),
            e.vested_amount,
            e.t0,
            e.p_entry,
        )
        for e in kept
    ]
    breaches = soft_vesting_breaches(
        events,
        vested,
        params.vesting,
        HarmonicOracle(
            inp.reserves,
            int(Fraction(str(params.vesting.unlock_twap_hours)) * 3600),
            params.prices.d_trust_lamports,
        ),
        cluster_of=clustered.cluster_of,
        excluded=inp.excluded,
        t_end=inp.t1,
    )
    # Cluster ids can change between epochs (merges), so prev.forfeit_until is not carried:
    # the replay of the full log under this epoch's map is the truth (DECISIONS D18).
    forfeit_until: dict[ClusterId, int] = dict(breaches.forfeit_until)
    # §11: score 0 "for the current epoch and the next 30": until = breach + 30 d, so
    # every epoch that starts before `until` is forfeited (31 daily epochs).
    forfeited = {cid for cid, until in forfeit_until.items() if until > inp.t0}
    unlocked = dict(prev.unlocked)
    for entry, value in zip(kept, breaches.unlocked, strict=True):
        unlocked[entry.wallet] = float(value)
    # §8 step 4
    twab_w = {w: twab_exact(0, paths.get(w, ()), inp.t0, inp.t1) for w in holder_list}
    twab_c = {
        cid: sum((twab_w.get(w, Fraction(0)) for w in members), Fraction(0))
        for cid, members in clustered.members.items()
    }
    # §8 step 5 — price-free supply-share eligibility (COIN_MATH v0.3.3 §2)
    eligible: set[ClusterId] = {
        cid
        for cid in clustered.members
        if is_eligible(twab_c[cid], inp.total_supply, params.eligibility.min_eligible_share)
        and cid not in forfeited
    }
    # §8 step 6 — v0.3.3 §3–§6: score = Σ over lots of (E1 + u·E2), u = 1 (boost off at
    # launch, §16). Lots come from the v0.3.3 ledger under this epoch's cluster map, as a
    # step function of the second, so lots sold mid-epoch still count for the time held.
    hold = params.hold
    knots = hold.knot_fractions()
    epoch_len = inp.t1 - inp.t0
    segments = ledger_segments(
        events,
        inp.excluded,
        inp.t0,
        inp.t1,
        cluster_of=clustered.cluster_of,
        taint_until=breaches.taint_until,
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
        eff_h = float(s_c / twab_c[cid]) if twab_c[cid] > 0 else 0.0
        s_c = s_c if cid in eligible else Fraction(0)
        raw_scores[cid] = s_c
        # hold = effective multiplier s_c / B̄_c; churn and boost are gone in v0.3.3 (1.0).
        rows[cid] = ClusterScore(cid, float(twab_c[cid]), eff_h, 1.0, 1.0, float(s_c), 0.0)
    for cid in forfeited & rows.keys():
        raw_scores[cid] = Fraction(0)
        row = rows[cid]
        rows[cid] = ClusterScore(cid, row.twab, row.hold, row.churn, row.boost, 0.0, 0.0)
    # §8 step 8
    pot = prev.pot + inp.pot_inflow
    budget = epoch_budget_v033(pot, Fraction(str(params.rewards.alpha_per_day)))
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
    # §8 step 10 / §13: credit this epoch's payouts onto the running balances, then pay
    # pending by push (each wallet whose pending reaches MIN_PAYOUT_Q) or by claims.
    book = credit_many(prev.balances, payouts)
    prev_carry = {w: int(v) for w, v in prev.carry.items() if int(v)}
    n_eligible = len(eligible - forfeited)
    transferred: dict[WalletId, int] = {}
    claims: dict[str, Any] | None = None
    push: tuple[tuple[WalletId, int], ...] = ()
    rail: Literal["push", "merkle", "none"] = "none"
    if skip or not any(b.pending for b in book.values()):
        book = prev.balances
    elif n_eligible < params.rewards.push_max_eligible:
        rail = "push"
        book, transferred = apply_push(book, params.rewards.push_min_transfer_lamports)
        push = tuple(transferred.items())
    else:
        rail = "merkle"
        due = {w: b.pending for w, b in book.items() if b.pending > 0}
        # TODO(#82 follow-up): carry the escrows in state for the 30/180-day pull-backs.
        book, _escrows = open_claims(book, due, inp.t1)
        transferred = dict(sorted(due.items()))
        claims = claims_document(transferred, version=prev.epoch)
    next_carry = {w: b.pending for w, b in book.items() if b.pending > 0}
    paid_total = {w: b.paid_total for w, b in book.items() if b.paid_total > 0}
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
        paid_total=dict(sorted(paid_total.items())),
    )
    return result, nxt
