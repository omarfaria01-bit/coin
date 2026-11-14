"""Golden 3-epoch replay and determinism tests (issue #52).

Float use (where it can affect integer payouts)
----------------------------------------------
Prices, TWAP, TWAB, hold H, churn F, underwater U and raw scores are IEEE-754
float64. ``capped_shares`` yields float π_c; ``allocate`` then does
``math.floor(budget * π_c)``. A 1-ulp change in a share sitting on an integer
boundary can move a payout by 1 (the remainder goes to rollover). Vesting
``unlocked`` is also float64; ``locked_amount`` uses ``math.ceil``, which can
flip a soft-lock breach and therefore later scores. Money fields in the golden
files (pot, payouts, carry, rollover, dust) are ints. Same float64 + the
engine's sort order ⇒ byte-identical artifacts on any machine. ``inputs_hash``
covers ``params.model_dump()`` (float fields as JSON numbers) plus the events
sorted by ``(slot, sig, ix)``, so a shuffle of input order must not change it.

Regenerate (after a deliberate, reviewed engine change only)::

    UPDATE_GOLDEN=1 uv run pytest tests/test_epoch_golden.py
"""

from __future__ import annotations

import os
import random
import shutil
from hashlib import sha256
from pathlib import Path

import base58

from adapters.epoch_files import write_epoch
from engine.epoch import EpochInputs, EpochResult, EpochState, empty_state, run_epoch
from engine.merkle import MerkleTree, build, leaf
from engine.params import CoinParams, EligibilityParams, RewardParams, VestingParams
from engine.types import EventKind, FirstFunding, PricePoint, SolTransfer, TokenEvent
from sim.agents import wallet_id

DAY = 86_400
INFLOW = 10**12
GOLDEN = Path(__file__).resolve().parent / "golden" / "epochs"
_FILES = ("result.json", "payouts.csv", "tree.json", "state.json", "inputs_hash.txt")


def W(label: str) -> str:
    return wallet_id(label)


def _sig(tag: str) -> str:
    return sha256(f"golden-epoch:{tag}".encode()).hexdigest()


def _params() -> CoinParams:
    # Pin fields that D14/D15 (and similar) may change on CoinParams defaults,
    # so a default-only bump cannot silently invalidate the committed goldens.
    return CoinParams(
        eligibility=EligibilityParams(min_eligible_usd=0.0, min_hold_hours=0.0),
        rewards=RewardParams(
            min_epoch_payout_lamports=0,
            push_min_transfer_lamports=1,
        ),
        vesting=VestingParams(unlock_twap_hours=24.0),
    )


def _buy(tag: str, wallet: str, amount: int, ts: int, ix: int = 0) -> TokenEvent:
    return TokenEvent(
        slot=ts + 1,
        ts=ts,
        sig=_sig(tag),
        ix=ix,
        kind=EventKind.BUY,
        src=None,
        dst=wallet,
        amount=amount,
        lamports=amount,
        fee_payer=wallet,
    )


def _xfer(tag: str, src: str, dst: str, amount: int, ts: int) -> TokenEvent:
    return TokenEvent(
        slot=ts + 1,
        ts=ts,
        sig=_sig(tag),
        ix=0,
        kind=EventKind.TRANSFER,
        src=src,
        dst=dst,
        amount=amount,
        lamports=None,
        fee_payer=src,
    )


def _sell(tag: str, src: str, amount: int, ts: int) -> TokenEvent:
    return TokenEvent(
        slot=ts + 1,
        ts=ts,
        sig=_sig(tag),
        ix=0,
        kind=EventKind.SELL,
        src=src,
        dst=None,
        amount=amount,
        lamports=amount,
        fee_payer=src,
    )


def _history() -> tuple[TokenEvent, ...]:
    a, b, c, d = W("ga"), W("gb"), W("gc"), W("gd")
    return (
        _buy("a0", a, 1_000_000_000, 100),
        _buy("b0", b, 2_000_000_000, 200),
        _buy("c0", c, 1_000_000_000, 300),
        _xfer("bd1", b, d, 500_000_000, DAY + 100),
        _sell("c1", c, 200_000_000, DAY + 200),
        _buy("d2", d, 1_000_000_000, 2 * DAY + 100),
        _buy("a2", a, 500_000_000, 2 * DAY + 200, ix=1),
    )


def _prices() -> tuple[PricePoint, ...]:
    # Sparse constant mid; covers the 1h lot-cost lookback and the 24h unlock TWAP.
    stamps = [-3_600, *range(0, 3 * DAY + 1, 6 * 3_600)]
    return tuple(PricePoint(ts, 1.0) for ts in stamps)


def _inputs(
    events: tuple[TokenEvent, ...], t0: int, t1: int, *, shuffle_seed: int | None
) -> EpochInputs:
    evs = list(e for e in events if e.ts <= t1)
    prices = list(p for p in _prices() if p.ts < t1)
    if shuffle_seed is not None:
        rng = random.Random(shuffle_seed)
        rng.shuffle(evs)
        rng.shuffle(prices)
    wallets = {e.dst or e.src for e in evs if (e.dst or e.src)}
    funds = tuple(FirstFunding(w, W(f"funder-{w[:8]}"), 0, 0) for w in sorted(wallets))
    sols = tuple(SolTransfer(1, 0, _sig(f"sol-{f.wallet}"), f.funder, f.wallet, 1) for f in funds)
    if shuffle_seed is not None:
        rng = random.Random(shuffle_seed + 1)
        funds_l, sols_l = list(funds), list(sols)
        rng.shuffle(funds_l)
        rng.shuffle(sols_l)
        funds, sols = tuple(funds_l), tuple(sols_l)
    return EpochInputs(
        t0=t0,
        t1=t1,
        slot_range=(1, t1 + 1),
        events=tuple(evs),
        sol_transfers=sols,
        fundings=funds,
        prices=tuple(prices),
        decimals=9,
        sol_usd=100.0,
        pot_inflow=INFLOW,
        excluded=frozenset(),
        hubs=frozenset(),
    )


def _tree(result: EpochResult) -> MerkleTree | None:
    if result.claims is None:
        return None
    leaves = [
        leaf(base58.b58decode(row["claimant"]), row["amount_unlocked"], row["amount_locked"])
        for row in result.claims["claims"]
    ]
    tree = build(leaves)
    if tree.root.hex() != result.claims["root"]:
        raise AssertionError("rebuilt merkle root does not match claims")
    return tree


def run_scenario(
    shuffle_seed: int | None = None,
) -> list[tuple[EpochResult, EpochState, MerkleTree | None]]:
    params = _params()
    history = _history()
    state = empty_state()
    out: list[tuple[EpochResult, EpochState, MerkleTree | None]] = []
    for i in range(3):
        inp = _inputs(history, i * DAY, (i + 1) * DAY, shuffle_seed=shuffle_seed)
        result, state = run_epoch(inp, params, state)
        out.append((result, state, _tree(result)))
    return out


def _write_golden(rows: list[tuple[EpochResult, EpochState, MerkleTree | None]]) -> None:
    if GOLDEN.exists():
        shutil.rmtree(GOLDEN)
    GOLDEN.mkdir(parents=True)
    (GOLDEN / "params.json").write_text(
        _params().model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    for result, state, tree in rows:
        write_epoch(GOLDEN, result, state, tree)


def test_params_pinned_in_golden() -> None:
    """Replay must use the committed params, not whatever CoinParams() defaults to today."""
    pinned = CoinParams.model_validate_json((GOLDEN / "params.json").read_text(encoding="utf-8"))
    assert pinned == _params()


def test_replay_matches_golden_bytes_and_inputs_hash(tmp_path: Path) -> None:
    rows = run_scenario()
    assert [r.epoch for r, _, _ in rows] == [0, 1, 2]
    hashes = [r.inputs_hash for r, _, _ in rows]
    assert all(hashes) and len(set(hashes)) == 3
    for result, state, tree in rows:
        dest = write_epoch(tmp_path, result, state, tree)
        golden = GOLDEN / str(result.epoch)
        assert (dest / "inputs_hash.txt").read_text(encoding="utf-8") == result.inputs_hash + "\n"
        for name in _FILES:
            assert (dest / name).read_bytes() == (golden / name).read_bytes(), name


def test_event_order_shuffle_is_byte_identical() -> None:
    base = run_scenario()
    shuffled = run_scenario(shuffle_seed=20261114)
    for (a, sa, ta), (b, sb, tb) in zip(base, shuffled, strict=True):
        assert a.inputs_hash == b.inputs_hash
        assert dict(a.payouts) == dict(b.payouts)
        assert a.pot == b.pot and a.rollover == b.rollover and a.dust == b.dust
        assert a.rail == b.rail and a.push == b.push
        assert dict(a.transferred_or_claimable) == dict(b.transferred_or_claimable)
        assert sa.pot == sb.pot and dict(sa.carry) == dict(sb.carry)
        assert (ta is None) == (tb is None)
        if ta is not None and tb is not None:
            assert ta.root == tb.root


def test_conservation_across_the_three_epochs() -> None:
    prev = empty_state()
    for result, nxt, _tree in run_scenario():
        lhs = prev.pot + INFLOW + sum(prev.carry.values())
        rhs = nxt.pot + sum(result.transferred_or_claimable.values()) + sum(nxt.carry.values())
        assert lhs == rhs
        prev = nxt
    assert prev.epoch == 3 and prev.pot < 3 * INFLOW


if os.environ.get("UPDATE_GOLDEN") == "1":  # pragma: no cover
    _write_golden(run_scenario())
