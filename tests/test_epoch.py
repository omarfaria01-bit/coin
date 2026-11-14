"""Tests for engine/epoch.py (ENGINE_DESIGN §8, COIN_MATH §14 rows 3 and 8)."""

from __future__ import annotations

import random
from dataclasses import replace
from hashlib import sha256

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.epoch import (
    EpochInputs,
    EpochState,
    VestingEntry,
    empty_state,
    run_epoch,
)
from engine.params import (
    CoinParams,
    EligibilityParams,
    RewardParams,
    ScoringParams,
)
from engine.rewards import epoch_budget
from engine.types import EventKind, FirstFunding, PricePoint, SolTransfer, TokenEvent
from sim.agents import wallet_id

T0, T1 = 0, 86_400
# Small supply so the default 1/1e6 floor is one base unit: these tests are not about dust.
TOTAL_SUPPLY = 1_000_000
LAMPORTS_PER_TOKEN = 1_000_000_000  # 1 SOL / whole token, decimals=9 → D13 = 1.0


def W(label: str) -> str:
    return wallet_id(label)


def _sig(tag: str) -> str:
    return sha256(f"epoch-test:{tag}".encode()).hexdigest()


def _params(
    *, cap: float = 1.0, enabled: bool = True, min_xfer: int = 1, push_max: int = 500
) -> CoinParams:
    return CoinParams(
        eligibility=EligibilityParams(min_eligible_share="0"),
        scoring=ScoringParams(cap=cap),
        rewards=RewardParams(
            enabled=enabled,
            min_epoch_payout_lamports=0,
            push_max_eligible=push_max,
            push_min_transfer_lamports=min_xfer,
        ),
    )


def _prices() -> tuple[PricePoint, ...]:
    return (PricePoint(-3_600, 1.0), PricePoint(T0, 1.0), PricePoint(T1 - 1, 1.0))


def _buy(label: str, wallet: str, amount: int, ts: int, ix: int = 0) -> TokenEvent:
    return TokenEvent(
        slot=ts + 1,
        ts=ts,
        sig=_sig(label),
        ix=ix,
        kind=EventKind.BUY,
        src=None,
        dst=wallet,
        amount=amount,
        lamports=amount,  # D13=1
        fee_payer=wallet,
    )


def _xfer(label: str, src: str, dst: str, amount: int, ts: int) -> TokenEvent:
    return TokenEvent(
        slot=ts + 1,
        ts=ts,
        sig=_sig(label),
        ix=0,
        kind=EventKind.TRANSFER,
        src=src,
        dst=dst,
        amount=amount,
        lamports=None,
        fee_payer=src,
    )


def _sell(label: str, src: str, amount: int, ts: int) -> TokenEvent:
    return TokenEvent(
        slot=ts + 1,
        ts=ts,
        sig=_sig(label),
        ix=0,
        kind=EventKind.SELL,
        src=src,
        dst=None,
        amount=amount,
        lamports=amount,
        fee_payer=src,
    )


def _inputs(events: list[TokenEvent], inflow: int = 10**12, fundings=None) -> EpochInputs:
    evs = tuple(events)
    wallets = {e.dst or e.src for e in evs if (e.dst or e.src)}
    funds = fundings or tuple(
        FirstFunding(w, W(f"funder-{w[:6]}"), T0, T0) for w in sorted(wallets)
    )
    sols = tuple(
        SolTransfer(T0 + 1, T0, _sig(f"sol-{f.wallet}"), f.funder, f.wallet, 1) for f in funds
    )
    return EpochInputs(
        t0=T0,
        t1=T1,
        slot_range=(1, T1 + 1),
        events=evs,
        sol_transfers=sols,
        fundings=tuple(funds),
        prices=_prices(),
        decimals=9,
        sol_usd=100.0,
        pot_inflow=inflow,
        total_supply=TOTAL_SUPPLY,
        excluded=frozenset(),
        hubs=frozenset(),
    )


def test_golden_three_equal_holders() -> None:
    """Hand-computed: 3 equal buyers, cap not binding (cap=1), R=10**11, exact §6 payout."""
    amount = 1_000_000_000
    wallets = [W("a"), W("b"), W("c")]
    events = [
        _buy(n, w, amount, T0, ix=i) for i, (n, w) in enumerate(zip("abc", wallets, strict=True))
    ]
    result, nxt = run_epoch(_inputs(events), _params(), empty_state())
    budget = epoch_budget(10**12, 0.10, 24)
    assert budget == 100_000_000_000
    # cap=1, equal scores → π=1/3, Σπ = 1 so T = R. Floors 33_333_333_333 each; the one
    # leftover unit goes by largest remainder, ties by smallest id (v0.3.3 §6, was rollover).
    expected = 33_333_333_333
    first = min(wallets)
    want = {w: expected + (1 if w == first else 0) for w in wallets}
    assert dict(result.payouts) == want
    assert result.rollover == 0
    assert result.dust == 0
    assert result.pot == 10**12 - budget
    assert result.rail == "push"
    assert result.push == tuple(sorted(want.items()))
    lhs = 0 + 10**12 + 0
    rhs = result.pot + sum(a for _, a in result.push) + sum(nxt.carry.values())
    assert lhs == rhs == 10**12
    assert nxt.epoch == 1


def test_rewards_disabled_zero_payouts_pot_gains_inflow() -> None:
    events = [_buy("a", W("a"), 1_000_000_000, T0)]
    prev = EpochState(0, 5_000, {}, {}, {}, ())
    result, nxt = run_epoch(_inputs(events, inflow=7_000), _params(enabled=False), prev)
    assert dict(result.payouts) == {}
    assert result.pot == 5_000 + 7_000
    assert nxt.pot == 12_000
    assert result.rail == "none"
    assert result.push == ()


def test_sniper_lot_under_t_start_scores_zero() -> None:
    holder, sniper = W("hold"), W("snipe")
    amt = 1_000_000_000
    events = [_buy("h", holder, amt, T0), _buy("s", sniper, amt, T1 - 300)]
    result, _nxt = run_epoch(_inputs(events), _params(), empty_state())
    rows = {row.cluster: row for row in result.scores}
    # Cluster id is the only wallet in each singleton cluster.
    # v0.3.3 §4: a lot younger than T_START = 2h scores exactly 0.
    assert rows[sniper].score == 0.0 and rows[holder].score > 0.0


def test_soft_vesting_transfer_then_sell_forfeits_cluster() -> None:
    vested, fresh, honest = W("vested"), W("fresh"), W("honest")
    amt = 1_000_000_000
    events = [
        _buy("v", vested, amt, T0),
        _buy("h", honest, amt, T0),
        _xfer("vf", vested, fresh, amt, 3_600),
        _sell("fs", fresh, amt, 7_200),
    ]
    prev = empty_state()
    prev = EpochState(
        0,
        0,
        {},
        {},
        {},
        (VestingEntry(vested, amt, 1.0, T0),),
    )
    result, nxt = run_epoch(_inputs(events), _params(), prev)
    # Vested wallet (and anyone clustered with it via the transfer) scores 0.
    vested_clusters = {row.cluster for row in result.scores if row.score > 0}
    assert honest in vested_clusters or any(
        r.cluster == honest and r.score > 0 for r in result.scores
    )
    for row in result.scores:
        if row.cluster != honest:
            assert row.score == 0.0
    assert result.payouts.get(vested, 0) == 0
    assert result.payouts.get(fresh, 0) == 0
    assert result.payouts.get(honest, 0) > 0
    assert honest in nxt.forfeit_until or any(nxt.forfeit_until.values())
    # Share of the forfeited cluster stays in the pot (conservation).
    lhs = 0 + 10**12
    rhs = result.pot + sum(result.transferred_or_claimable.values()) + sum(nxt.carry.values())
    assert lhs == rhs


def test_push_carry_below_min_transfer_paid_next_epoch() -> None:
    w = W("solo")
    events = [_buy("s", w, 1_000_000_000, T0)]
    # Huge min_transfer → this epoch's payout is carried.
    p = _params(min_xfer=10**18)
    result, mid = run_epoch(_inputs(events, inflow=10**12), p, empty_state())
    assert result.payouts[w] > 0
    assert result.push == ()
    assert mid.carry[w] == result.payouts[w]
    # Second epoch: same inflow, carry + new payout exceeds a small min (still huge? lower it).
    p2 = _params(min_xfer=1)
    result2, nxt = run_epoch(_inputs(events, inflow=10**12), p2, mid)
    paid = result2.transferred_or_claimable[w]
    assert paid == result2.payouts[w] + mid.carry[w]
    assert result2.push == ((w, paid),)
    assert nxt.carry == {}
    assert mid.pot + 10**12 + mid.carry[w] == result2.pot + paid


def test_determinism_shuffled_events() -> None:
    wallets = [W("d1"), W("d2"), W("d3")]
    events = [_buy(f"x{i}", w, 1_000_000_000 + i, T0, ix=i) for i, w in enumerate(wallets)]
    a, na = run_epoch(_inputs(events), _params(), empty_state())
    shuffled = list(events)
    random.Random(0).shuffle(shuffled)
    b, nb = run_epoch(_inputs(shuffled), _params(), empty_state())
    assert a.inputs_hash == b.inputs_hash
    assert dict(a.payouts) == dict(b.payouts)
    assert a.rail == b.rail and a.push == b.push
    assert na.pot == nb.pot and dict(na.carry) == dict(nb.carry)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(1_000_000, 50_000_000), min_size=2, max_size=5))
def test_conservation_random_small_worlds(amounts: list[int]) -> None:
    events = [_buy(f"r{i}", W(f"r{i}"), amt, T0, ix=i) for i, amt in enumerate(amounts)]
    result, nxt = run_epoch(_inputs(events, inflow=10**9), _params(), empty_state())
    lhs = 0 + 10**9
    rhs = result.pot + sum(result.transferred_or_claimable.values()) + sum(nxt.carry.values())
    assert lhs == rhs


def test_merkle_rail_when_eligible_reaches_push_max() -> None:
    wallets = [W("m1"), W("m2")]
    events = [_buy(f"m{i}", w, 1_000_000_000, T0, ix=i) for i, w in enumerate(wallets)]
    result, nxt = run_epoch(_inputs(events), _params(push_max=0), empty_state())
    assert result.rail == "merkle"
    assert result.claims is not None
    assert result.claims["root"]
    assert result.push == ()
    assert nxt.carry == {}
    assert sum(result.transferred_or_claimable.values()) == sum(result.payouts.values())


def test_rejects_bad_window_and_negative_pot() -> None:
    events = [_buy("a", W("a"), 1_000_000_000, T0)]
    inp = _inputs(events)
    bad = replace(inp, t1=inp.t0 + 10)
    with pytest.raises(ValueError, match="t1-t0"):
        run_epoch(bad, _params(), empty_state())
    with pytest.raises(ValueError, match="pot"):
        run_epoch(inp, _params(), EpochState(0, -1, {}, {}, {}, ()))


def test_total_supply_is_required_and_positive() -> None:
    inp = _inputs([_buy("a", W("a"), 10, T0, ix=0)])
    with pytest.raises(ValueError, match="total_supply"):
        replace(inp, total_supply=0)
    with pytest.raises(TypeError, match="total_supply"):
        replace(inp, total_supply=True)


def test_lot_sold_mid_epoch_scores_for_the_time_held_and_payout_is_exact() -> None:
    keeper, seller = W("keep"), W("sell")
    amt = 1_000_000_000
    events = [
        _buy("k", keeper, amt, T0 - 100 * 86_400, ix=0),
        _buy("s", seller, amt, T0 - 100 * 86_400, ix=1),
        TokenEvent(T1 // 2, T1 // 2, _sig("sold"), 0, EventKind.SELL, seller, None, amt, 1, seller),
    ]
    result, _nxt = run_epoch(_inputs(events), _params(), empty_state())
    rows = {row.cluster: row for row in result.scores}
    # Flat h (lots > 90d old), held half the epoch → exactly half the score.
    assert rows[seller].score * 2 == pytest.approx(rows[keeper].score, rel=1e-12)
    budget = epoch_budget(10**12, 0.10, 24)
    assert sum(result.payouts.values()) + result.rollover == budget


# --- #82 PR3: v0.3.3 sybil clustering + soft-vesting wiring, end to end through run_epoch ---

FORFEIT_S = 30 * 86_400
AMT = 1_000_000_000


def _vest(wallet: str, amount: int = AMT) -> EpochState:
    return EpochState(0, 0, {}, {}, {}, (VestingEntry(wallet, amount, 1.0, T0),))


def test_run_epoch_breach_forfeits_cluster_and_fills_unlocked() -> None:
    vested, honest = W("v-breach"), W("h-breach")
    events = [_buy("vb", vested, AMT, T0), _buy("hb", honest, AMT, T0, ix=1)]
    events.append(_sell("vs", vested, AMT // 2, 3_600))  # 1h in: u_time = 1/168 → locked
    result, nxt = run_epoch(_inputs(events), _params(), _vest(vested))
    rows = {r.cluster: r for r in result.scores}
    assert rows[vested].score == 0.0 and rows[vested].share == 0.0
    assert rows[honest].score > 0.0
    assert result.payouts.get(vested, 0) == 0 and result.payouts[honest] > 0
    assert nxt.forfeit_until == {vested: 3_600 + FORFEIT_S}
    assert nxt.unlocked == {vested: pytest.approx(1 / 7)}  # time unlock only at t1 = 1 day


def test_run_epoch_no_breach_keeps_score() -> None:
    vested = W("v-ok")
    events = [_buy("vo", vested, AMT, T0), _sell("vos", vested, AMT // 1000, 3_600)]
    result, nxt = run_epoch(_inputs(events), _params(), _vest(vested, AMT // 2))
    assert nxt.forfeit_until == {}
    assert result.scores[0].score > 0.0


def test_run_epoch_taint_zeroes_received_lots_only() -> None:
    """Locked tokens sent to another cluster score 0 there; the receiver's own lot is untouched."""
    vested, recv, honest = W("v-taint"), W("r-taint"), W("h-taint")
    events = [
        _buy("vt", vested, AMT, T0),
        _buy("rt", recv, AMT, T0, ix=1),
        _buy("ht", honest, AMT, T0, ix=2),
        _xfer("leak", vested, recv, AMT, 3_600),
    ]
    result, nxt = run_epoch(_inputs(events), _params(), _vest(vested))
    rows = {r.cluster: r for r in result.scores}
    assert {vested, recv, honest} <= rows.keys()  # one transfer alone does not merge (§7)
    assert nxt.forfeit_until == {vested: 3_600 + FORFEIT_S}
    assert rows[vested].score == 0.0
    # recv holds 2·AMT but the leaked lot is tainted → same score as honest's single lot.
    assert rows[recv].score == pytest.approx(rows[honest].score, rel=1e-12)


def test_run_epoch_signers_and_overrides_merge_clusters() -> None:
    a, b, c, d = sorted(W(x) for x in ("m-a", "m-b", "m-c", "m-d"))
    events = [_buy(f"m{i}", w, AMT, T0, ix=i) for i, w in enumerate((a, b, c, d))]
    inp = replace(
        _inputs(events),
        signers={_sig("cosign"): frozenset({b, d})},  # S1
        overrides=((a, c, "ov-1"),),  # S3
    )
    result, _ = run_epoch(inp, _params(), empty_state())
    assert [r.cluster for r in result.scores] == [a, b]  # id = smallest holder of the cluster
    assert sum(result.payouts.values()) + result.rollover == epoch_budget(10**12, 0.10, 24)


def test_forfeit_follows_cluster_whose_id_changes_between_epochs() -> None:
    """Epoch 1: V breaches (cluster id V). Epoch 2: a smaller holder A joins V's cluster, so the
    id becomes A. The forfeit must follow (key A), with no stale V key; a stale prev key on an
    honest cluster must not forfeit it (the replay, not prev.forfeit_until, is the truth)."""
    a, v = sorted(W(x) for x in ("id-a", "id-v"))
    honest = W("id-h")
    e1 = [
        _buy("iv", v, AMT, T0),
        _buy("ih", honest, AMT, T0, ix=1),
        _sell("ivs", v, AMT // 2, 3_600),
    ]
    _, mid = run_epoch(_inputs(e1), _params(), _vest(v))
    until = 3_600 + FORFEIT_S
    assert mid.forfeit_until == {v: until}
    e2 = [*e1, _buy("ia", a, AMT, T1 + 60)]
    inp2 = replace(
        _inputs(e2),
        t0=T1,
        t1=2 * T1,
        slot_range=(T1 + 1, 2 * T1 + 1),
        overrides=((a, v, "ov-id"),),
    )
    stale = replace(mid, forfeit_until={**mid.forfeit_until, honest: 10**12})
    result, nxt = run_epoch(inp2, _params(), stale)
    rows = {r.cluster: r for r in result.scores}
    assert v not in rows and rows[a].score == 0.0
    assert rows[honest].score > 0.0 and result.payouts[honest] > 0
    assert nxt.forfeit_until == {a: until}
