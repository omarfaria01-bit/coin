"""Hypothesis fuzz over the full ``run_epoch`` (issue #150).

For random *valid* inputs — events (buys/sells/transfers), swap-print prices, running
balances, pot, vesting — every epoch must:

* conserve value (COIN_MATH v0.3.3 §8/§13):
  ``budget + locks_before == remainder + released + locks_after``;
* keep every amount an exact non-negative ``int`` (no floats, no bools);
* keep the §13 book coherent (``earned_total == paid_total + pending``);
* honour the payout rail (push / merkle / none) it reports;
* be deterministic: same inputs → same result and state.

The generator replays its own holdings while drawing, so it never asks the ledger for an
oversell and never needs ``hypothesis`` filtering. Runtime is kept under a minute.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, replace
from fractions import Fraction

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.epoch import EpochInputs, EpochResult, EpochState, VestingEntry, run_epoch
from engine.params import CoinParams, EligibilityParams, RewardParams, ScoringParams
from engine.prices import ReservePoint
from engine.rewards import epoch_budget_v033
from engine.types import EventKind, FirstFunding, PricePoint, SolTransfer, TokenEvent
from sim.agents import wallet_id

DAY = 86_400
FUZZ = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@dataclass(frozen=True, slots=True)
class _Case:
    inp: EpochInputs
    params: CoinParams
    prev: EpochState
    seed: int


def _sig(tag: str) -> str:
    return hashlib.sha256(f"epoch-fuzz-150:{tag}".encode()).hexdigest()


def _params(
    cap: float, alpha: float, enabled: bool, min_pot: int, push_max: int, min_xfer: int
) -> CoinParams:
    return CoinParams(
        eligibility=EligibilityParams(min_eligible_share="0"),
        scoring=ScoringParams(cap=cap),
        rewards=RewardParams(
            enabled=enabled,
            alpha_per_day=alpha,
            min_epoch_payout_lamports=min_pot,
            push_max_eligible=push_max,
            push_min_transfer_lamports=min_xfer,
        ),
    )


@st.composite
def _prev_state(draw) -> EpochState:
    wallets = [wallet_id(f"fz150-prev-{i}") for i in range(draw(st.integers(0, 3)))]
    carry = {w: draw(st.integers(1, 10**10)) for w in wallets if draw(st.booleans())}
    paid = {w: draw(st.integers(0, 10**10)) for w in wallets if draw(st.booleans())}
    return EpochState(
        epoch=draw(st.integers(0, 4)),
        pot=draw(st.integers(0, 10**12)),
        carry=carry,
        forfeit_until={},
        unlocked={},
        vesting=(),
        paid_total=paid,
    )


@st.composite
def epoch_case(draw) -> _Case:
    """One valid epoch window plus running state. Holdings are replayed while drawing."""
    n = draw(st.integers(2, 5))
    wallets = [wallet_id(f"fz150-w{i}") for i in range(n)]
    t0 = draw(st.integers(0, 5)) * DAY
    t1 = t0 + DAY
    holdings = dict.fromkeys(wallets, 0)
    events: list[TokenEvent] = []
    seq = 0

    def emit(
        kind: EventKind,
        src: str | None,
        dst: str | None,
        amount: int,
        lamports: int | None,
        ts: int,
    ) -> None:
        nonlocal seq
        seq += 1
        events.append(
            TokenEvent(0, ts, _sig(f"{seq}:{ts}"), 0, kind, src, dst, amount, lamports, src or dst)
        )

    # One pre-epoch pool buy per wallet (history, so lots have age at t0).
    for w in wallets:
        amount = draw(st.integers(1, 10**9))
        holdings[w] += amount
        emit(EventKind.BUY, None, w, amount, amount, t0 - draw(st.integers(60, 3 * DAY)))

    # In-epoch actions, chronological; amounts bounded by the replayed holdings.
    offsets = sorted(draw(st.lists(st.integers(0, DAY - 1), max_size=8, unique=True)))
    for off in offsets:
        choices = ["buy"]
        if any(holdings.values()):
            choices.append("sell")
            if n > 1:
                choices.append("transfer")
        action = draw(st.sampled_from(choices))
        ts = t0 + off
        if action == "buy":
            w = draw(st.sampled_from(wallets))
            amount = draw(st.integers(1, 10**9))
            holdings[w] += amount
            emit(EventKind.BUY, None, w, amount, amount, ts)
        elif action == "sell":
            src = draw(st.sampled_from([w for w in wallets if holdings[w] > 0]))
            amount = draw(st.integers(1, holdings[src]))
            holdings[src] -= amount
            emit(EventKind.SELL, src, None, amount, amount, ts)
        else:
            src = draw(st.sampled_from([w for w in wallets if holdings[w] > 0]))
            dst = draw(st.sampled_from([w for w in wallets if w != src]))
            amount = draw(st.integers(1, holdings[src]))
            holdings[src] -= amount
            holdings[dst] += amount
            emit(EventKind.TRANSFER, src, dst, amount, None, ts)

    events.sort(key=lambda e: (e.ts, e.sig))
    stamped = tuple(replace(e, slot=i + 1) for i, e in enumerate(events))

    fundings = tuple(
        FirstFunding(w, wallets[(i + 1) % n], t0 - 2 * DAY, t0 - 2 * DAY)
        for i, w in enumerate(wallets)
    )
    sol_transfers = tuple(
        SolTransfer(i + 1, t0 - DAY, _sig(f"sol{i}"), wallets[i % n], wallets[(i + 1) % n], 10**9)
        for i in range(draw(st.integers(0, 3)))
    )
    prices = tuple(
        PricePoint(t0 + i * 3_600, draw(st.sampled_from([0.01, 1.0, 7.5]))) for i in range(3)
    )
    vesting: tuple[VestingEntry, ...] = ()
    if draw(st.booleans()):
        w = draw(st.sampled_from(wallets))
        vesting = (
            VestingEntry(
                w,
                draw(st.integers(1, 10**9)),
                draw(st.sampled_from(["1", "1/2", "2"])),
                t0 - draw(st.integers(0, 2 * 3_600)),
            ),
        )
    reserves: tuple[ReservePoint, ...] = ()
    if draw(st.booleans()):
        reserves = (
            ReservePoint(t0 - 3 * DAY, 10**14, 10**12),
            ReservePoint(t0 - DAY, 12 * 10**13, 10**12),
        )
    signers = {}
    if draw(st.booleans()):
        signers[_sig("cosign")] = frozenset(
            draw(st.lists(st.sampled_from(wallets), min_size=2, max_size=n))
        )
    overrides = ()
    if draw(st.booleans()):
        a, b = draw(st.lists(st.sampled_from(wallets), min_size=2, max_size=2, unique=True))
        overrides = ((a, b, "ov-150"),)
    hubs = frozenset() if draw(st.booleans()) else frozenset({wallets[0]})
    inp = EpochInputs(
        t0=t0,
        t1=t1,
        slot_range=(stamped[0].slot, stamped[-1].slot),
        events=stamped,
        sol_transfers=sol_transfers,
        fundings=fundings,
        prices=prices,
        decimals=9,
        sol_usd=draw(st.sampled_from([1.0, 150.0])),
        pot_inflow=draw(st.integers(0, 10**12)),
        excluded=frozenset(),
        hubs=hubs,
        total_supply=draw(st.integers(1, 10**15)),
        signers=signers,
        overrides=overrides,
        reserves=reserves,
    )
    params = _params(
        cap=draw(st.sampled_from([0.05, 0.2, 0.5, 1.0])),
        alpha=draw(st.sampled_from([0.1, 0.25, 0.5, 1.0])),
        enabled=draw(st.sampled_from([True, True, True, False])),
        min_pot=draw(st.sampled_from([0, 0, 0, 1, 10**9])),
        push_max=draw(st.sampled_from([0, 1, 500])),
        min_xfer=draw(st.sampled_from([0, 1, 10**6, 5_000_000])),
    )
    prev = replace(draw(_prev_state()), vesting=vesting)
    return _Case(inp, params, prev, draw(st.integers()))


def _money(value: object, label: str) -> int:
    assert type(value) is int, f"{label}: amount must be an int, got {type(value).__name__}"
    assert value >= 0, f"{label}: amount must be >= 0, got {value}"
    return value


def _check_epoch(case: _Case, prev: EpochState, result: EpochResult, nxt: EpochState) -> None:
    inp, params = case.inp, case.params
    pot = prev.pot + inp.pot_inflow
    budget = epoch_budget_v033(pot, Fraction(str(params.rewards.alpha_per_day)))
    skip = (not params.rewards.enabled) or budget < params.rewards.min_epoch_payout_lamports
    payout_sum = _money(sum(result.payouts.values()), "Σ payouts")
    released = _money(sum(result.transferred_or_claimable.values()), "Σ released")
    locks_before = _money(sum(prev.carry.values()), "Σ prev locks")
    locks_after = _money(sum(nxt.carry.values()), "Σ next locks")
    # Amounts declared by the epoch but not paid stay in the pot ("remainder").
    remainder = budget if skip else _money(result.rollover + result.dust, "remainder")

    # §8 conservation, both as the engine states it and as budget + locks.
    assert pot + locks_before == nxt.pot + released + locks_after
    assert budget + locks_before == remainder + released + locks_after
    assert nxt.pot == result.pot == pot - payout_sum
    _money(result.pot, "pot")
    _money(result.rollover, "rollover")
    _money(result.dust, "dust")

    if skip:
        assert result.payouts == {} and result.rollover == 0 and result.dust == 0
        assert result.rail == "none" and result.push == () and result.transferred_or_claimable == {}
        assert nxt.carry == {w: v for w, v in prev.carry.items() if v > 0}
        assert nxt.paid_total == {w: v for w, v in prev.paid_total.items() if v > 0}
    else:
        assert payout_sum + result.rollover + result.dust == budget
        assert payout_sum <= budget

    for wallet, amount in (
        *result.payouts.items(),
        *result.transferred_or_claimable.items(),
        *nxt.carry.items(),
        *nxt.paid_total.items(),
    ):
        _money(amount, f"amount[{wallet}]")
    assert all(v > 0 for v in nxt.carry.values())
    assert all(v > 0 for v in nxt.paid_total.values())
    assert all(v > 0 for v in result.payouts.values())
    assert all(v > 0 for v in result.transferred_or_claimable.values())

    # §13 running book: no negative pending, earned = paid + pending, page frozen.
    for wallet in set(nxt.carry) | set(nxt.paid_total):
        bal = nxt.balances[wallet]
        assert bal.earned_total == bal.paid_total + nxt.carry.get(wallet, 0)
        assert bal.paid_total == nxt.paid_total.get(wallet, 0)
        _money(bal.paid_total, f"paid_total[{wallet}]")
    assert result.epoch == prev.epoch and nxt.epoch == prev.epoch + 1

    # The reported rail must match the amounts it says it paid out.
    if result.rail == "push":
        assert result.claims is None
        assert dict(result.push) == dict(result.transferred_or_claimable)
        threshold = params.rewards.push_min_transfer_lamports
        assert all(
            amount >= max(threshold, 1) for amount in result.transferred_or_claimable.values()
        )
    elif result.rail == "merkle":
        assert result.push == () and nxt.carry == {} and result.claims is not None
        rows = result.claims["claims"]
        assert len(rows) == len(result.transferred_or_claimable)
        assert sum(row["amount_unlocked"] for row in rows) == released
        assert all(row["amount_locked"] == 0 for row in rows)
    else:
        assert result.push == () and result.claims is None and released == 0

    # Scores are non-negative and the whale cap keeps the share mass ≤ 1.
    assert all(row.score >= 0.0 and 0.0 <= row.share <= 1.0 for row in result.scores)
    assert sum(row.share for row in result.scores) <= 1.0 + 1e-9
    assert isinstance(result.inputs_hash, str) and len(result.inputs_hash) == 64
    int(result.inputs_hash, 16)


def _fingerprint(result: EpochResult, nxt: EpochState) -> str:
    payload = {
        "payouts": result.payouts,
        "scores": [(r.cluster, r.score, r.share) for r in result.scores],
        "rollover": result.rollover,
        "dust": result.dust,
        "pot": result.pot,
        "rail": result.rail,
        "claims": result.claims,
        "push": result.push,
        "review": result.review,
        "transferred": result.transferred_or_claimable,
        "inputs_hash": result.inputs_hash,
        "state": {
            "epoch": nxt.epoch,
            "pot": nxt.pot,
            "carry": nxt.carry,
            "paid_total": nxt.paid_total,
            "forfeit_until": nxt.forfeit_until,
            "unlocked": dict(sorted(nxt.unlocked.items())),
        },
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


@FUZZ
@given(epoch_case())
def test_fuzz_epoch_conserves_every_amount(case: _Case) -> None:
    result, nxt = run_epoch(case.inp, case.params, case.prev)
    _check_epoch(case, case.prev, result, nxt)


@FUZZ
@given(epoch_case())
def test_fuzz_epoch_is_deterministic_for_the_same_input(case: _Case) -> None:
    first = run_epoch(case.inp, case.params, case.prev)
    second = run_epoch(case.inp, case.params, case.prev)
    assert first == second
    assert _fingerprint(*first) == _fingerprint(*second)


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(epoch_case())
def test_fuzz_epoch_is_insensitive_to_event_order(case: _Case) -> None:
    shuffled = list(case.inp.events)
    random.Random(case.seed).shuffle(shuffled)
    result, nxt = run_epoch(replace(case.inp, events=tuple(shuffled)), case.params, case.prev)
    (reference, ref_state) = run_epoch(case.inp, case.params, case.prev)
    assert _fingerprint(result, nxt) == _fingerprint(reference, ref_state)


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(epoch_case(), st.integers(0, 10**12))
def test_fuzz_two_epoch_chain_never_loses_a_lamport(case: _Case, next_inflow: int) -> None:
    prev = case.prev
    result0, state0 = run_epoch(case.inp, case.params, prev)
    _check_epoch(case, prev, result0, state0)
    inp1 = replace(
        case.inp,
        t0=case.inp.t0 + DAY,
        t1=case.inp.t1 + DAY,
        pot_inflow=next_inflow,
    )
    result1, state1 = run_epoch(inp1, case.params, state0)
    _check_epoch(replace(case, inp=inp1), state0, result1, state1)

    paid0 = sum(result0.transferred_or_claimable.values())
    paid1 = sum(result1.transferred_or_claimable.values())
    earned0 = sum(result0.payouts.values())
    earned1 = sum(result1.payouts.values())
    # Every lock carried in, earned or released stays accounted for across both epochs.
    assert sum(prev.carry.values()) + earned0 + earned1 == paid0 + paid1 + sum(
        state1.carry.values()
    )
    assert sum(state1.paid_total.values()) == sum(prev.paid_total.values()) + paid0 + paid1
