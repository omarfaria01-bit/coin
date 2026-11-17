"""Full-epoch conservation fuzz over run_epoch (issue #150).

Random valid worlds (buys, transfers, sells, prior pot/carry/paid state, both payout rails):
every amount is conserved, nothing is negative or a float, and the run is deterministic.
"""

from __future__ import annotations

from fractions import Fraction
from hashlib import sha256

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.epoch import EpochInputs, EpochResult, EpochState, run_epoch
from engine.params import CoinParams, EligibilityParams, RewardParams, ScoringParams
from engine.rewards import epoch_budget_v033
from engine.types import EventKind, FirstFunding, PricePoint, SolTransfer, TokenEvent
from sim.agents import wallet_id

T0, T1 = 0, 86_400
TOTAL_SUPPLY = 1_000_000
N_WALLETS = 6
WALLETS = [wallet_id(f"fuzz-{i}") for i in range(N_WALLETS)]


def _sig(i: int) -> str:
    return sha256(f"epoch-fuzz:{i}".encode()).hexdigest()


@st.composite
def worlds(draw: st.DrawFn) -> tuple[tuple[TokenEvent, ...], EpochState, int, CoinParams]:
    """Events are generated in time order against running balances, so sells and
    transfers never overdraw."""
    n_events = draw(st.integers(0, 14))
    times = sorted(draw(st.lists(st.integers(T0, T1 - 1), min_size=n_events, max_size=n_events)))
    bal = dict.fromkeys(WALLETS, 0)
    events: list[TokenEvent] = []
    for i, ts in enumerate(times):
        w = WALLETS[draw(st.integers(0, N_WALLETS - 1))]
        kind = draw(st.sampled_from(["buy", "buy", "sell", "xfer"]))
        if kind != "buy" and bal[w] == 0:
            kind = "buy"
        base = dict(slot=ts * 20 + i + 1, ts=ts, sig=_sig(i), ix=0)
        if kind == "buy":
            amt = draw(st.integers(1, 10**9))
            bal[w] += amt
            events.append(
                TokenEvent(
                    **base,
                    kind=EventKind.BUY,
                    src=None,
                    dst=w,
                    amount=amt,
                    lamports=amt,
                    fee_payer=w,
                )
            )
        elif kind == "sell":
            amt = draw(st.integers(1, bal[w]))
            bal[w] -= amt
            events.append(
                TokenEvent(
                    **base,
                    kind=EventKind.SELL,
                    src=w,
                    dst=None,
                    amount=amt,
                    lamports=amt,
                    fee_payer=w,
                )
            )
        else:
            dst = WALLETS[draw(st.integers(0, N_WALLETS - 1))]
            if dst == w:
                continue
            amt = draw(st.integers(1, bal[w]))
            bal[w] -= amt
            bal[dst] += amt
            events.append(
                TokenEvent(
                    **base,
                    kind=EventKind.TRANSFER,
                    src=w,
                    dst=dst,
                    amount=amt,
                    lamports=None,
                    fee_payer=w,
                )
            )
    carry_w = draw(st.lists(st.sampled_from(WALLETS), unique=True, max_size=3))
    carry = {w: draw(st.integers(1, 10**9)) for w in carry_w}
    paid = {
        w: draw(st.integers(1, 10**9)) for w in draw(st.lists(st.sampled_from(WALLETS), max_size=3))
    }
    prev = EpochState(
        epoch=draw(st.integers(0, 5)),
        pot=draw(st.integers(0, 10**13)),
        carry=carry,
        forfeit_until={},
        unlocked={},
        vesting=(),
        paid_total=paid,
    )
    inflow = draw(st.integers(0, 10**13))
    params = CoinParams(
        eligibility=EligibilityParams(min_eligible_share="0"),
        scoring=ScoringParams(cap=draw(st.sampled_from([0.25, 0.5, 1.0]))),
        rewards=RewardParams(
            enabled=draw(st.booleans()),
            min_epoch_payout_lamports=0,
            push_max_eligible=draw(st.sampled_from([1, 3, 500])),  # small → merkle rail
            push_min_transfer_lamports=draw(st.sampled_from([1, 10**5, 5 * 10**6])),
        ),
    )
    return tuple(events), prev, inflow, params


def _inputs(events: tuple[TokenEvent, ...], inflow: int) -> EpochInputs:
    wallets = sorted({w for e in events for w in (e.src, e.dst) if w})
    funds = tuple(FirstFunding(w, wallet_id(f"funder-{w[:6]}"), T0, T0) for w in wallets)
    sols = tuple(
        SolTransfer(T0 + 1, T0, _sig(10_000 + i), f.funder, f.wallet, 1)
        for i, f in enumerate(funds)
    )
    return EpochInputs(
        t0=T0,
        t1=T1,
        slot_range=(1, T1 * 20 + 20),
        events=events,
        sol_transfers=sols,
        fundings=funds,
        prices=(PricePoint(T0, 1.0), PricePoint(T1 - 1, 1.0)),
        decimals=9,
        sol_usd=100.0,
        pot_inflow=inflow,
        total_supply=TOTAL_SUPPLY,
        excluded=frozenset(),
        hubs=frozenset(),
    )


def _all_ints(result: EpochResult, state: EpochState) -> list[object]:
    return [
        result.rollover,
        result.dust,
        result.pot,
        state.pot,
        *result.payouts.values(),
        *result.transferred_or_claimable.values(),
        *(a for _, a in result.push),
        *state.carry.values(),
        *state.paid_total.values(),
    ]


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(worlds())
def test_run_epoch_conserves_everything(world) -> None:
    events, prev, inflow, params = world
    inp = _inputs(events, inflow)
    result, nxt = run_epoch(inp, params, prev)

    # No floats, no negatives, no bools masquerading as amounts.
    for v in _all_ints(result, nxt):
        assert type(v) is int
        assert v >= 0

    # Whole-system conservation: pot + prior carry + inflow == new pot + moved + new carry.
    lhs = prev.pot + inflow + sum(prev.carry.values())
    rhs = nxt.pot + sum(result.transferred_or_claimable.values()) + sum(nxt.carry.values())
    assert lhs == rhs
    assert result.pot == nxt.pot
    assert nxt.epoch == prev.epoch + 1

    # Budget split: payouts + remainder == budget when paying; nothing leaves the pot otherwise.
    pot = prev.pot + inflow
    paid = sum(result.payouts.values())
    if params.rewards.enabled:
        budget = epoch_budget_v033(pot, Fraction(str(params.rewards.alpha_per_day)))
        assert paid + result.rollover == budget
        assert nxt.pot == pot - paid
    else:
        assert paid == 0
        assert nxt.pot == pot

    # Locks (carry) never go negative and paid_total only grows.
    for w, v in prev.paid_total.items():
        assert nxt.paid_total.get(w, 0) >= v

    # Determinism: same input + params + state -> identical result and state.
    result2, nxt2 = run_epoch(inp, params, prev)
    assert result2 == result
    assert nxt2 == nxt
