"""D39 (audit #271 H3/M1/M4): commit → reveal, verifier, idempotent payouts."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from engine.draw_commit import (
    DrawInputs,
    DrawMismatch,
    _canon,
    inputs_from_public,
    resolve_draw,
    snapshot_hash,
    verify_draw,
    vrf_seed,
    wallet_prizes,
)
from engine.payout_guard import (
    UnresolvedIntent,
    payment_key,
    pending_sends,
    verified_draw_payouts,
)

ROOT = Path(__file__).resolve().parents[1]
S = 10**15
RHO = bytes(range(32))


def inputs(**kw) -> DrawInputs:
    groups = {f"g{i:03d}": Fraction(S // 1000 * 5) for i in range(120)}
    base = DrawInputs(
        mint=b"m" * 32,
        genesis_hash=b"g" * 32,
        draw_index=42,
        cutoff_slot=300_000_000,
        cutoff_ts=1_795_000_000,
        total_supply=S,
        pot=2 * 10**9,
        prize_bps=(4000, 1000, 1000, 1000, 500, 500, 500, 500, 500, 500),
        scores=groups,
        balances={g: Fraction(S // 1000) for g in groups},
        wallet_scores={"g000": {"w1": Fraction(1), "w2": Fraction(3)}},
        overrides=(("a", "b", "ov1"),),
        hubs=frozenset({"CEX1"}),
        excluded=frozenset({"POOL", "DEV"}),
        params={
            "cap": "1/20",
            "supply_cap": "1/20",
            "min_holding_share": "1/10000",
            "min_groups": 100,
            "min_pot": 10_000_000,
        },  # fmt: skip
    )
    return replace(base, **kw)


def test_every_input_changes_the_hash() -> None:
    h = snapshot_hash(inputs())
    assert len(h) == 32 and vrf_seed(h) == h
    for change in (
        {"overrides": ()},
        {"hubs": frozenset({"CEX2"})},
        {"excluded": frozenset({"POOL"})},
        {"cutoff_slot": 300_000_001},
        {"cutoff_ts": 1},
        {"params": {"cap": "1/10"}},
        {"pot": 1},
        {"draw_index": 43},
    ):
        assert snapshot_hash(inputs(**change)) != h, change


def test_public_json_round_trips_to_the_same_hash() -> None:
    i = inputs()
    body = json.loads(i.canonical())
    assert snapshot_hash(inputs_from_public(body)) == snapshot_hash(i)


def test_mismatch_raises_and_no_retry_rolls_over() -> None:
    i = inputs()
    h = snapshot_hash(i)
    with pytest.raises(DrawMismatch):
        resolve_draw(replace(i, pot=3), h, RHO, vrf_requests=1)
    for n, rho, reason in ((2, RHO, "vrf_retry_forbidden"), (1, None, "vrf_unfulfilled"),
                           (0, None, "vrf_unfulfilled")):  # fmt: skip
        p = resolve_draw(i, h, rho, vrf_requests=n)
        assert (p.drawn, p.reason, p.rollover) == (False, reason, i.pot)
    assert resolve_draw(i, h, RHO, vrf_requests=1).drawn


def test_verifier_accepts_the_truth_and_rejects_any_change() -> None:
    i = inputs()
    h = snapshot_hash(i)
    p = resolve_draw(i, h, RHO, vrf_requests=1)
    ok = {"claimed_winners": list(p.winners), "claimed_prizes": p.prizes,
          "claimed_rollover": p.rollover}  # fmt: skip
    verify_draw(i, h, RHO, vrf_requests=1, **ok)
    bad = dict(ok, claimed_winners=list(reversed(p.winners)))
    with pytest.raises(DrawMismatch):
        verify_draw(i, h, RHO, vrf_requests=1, **bad)
    with pytest.raises(DrawMismatch):
        verify_draw(i, h, bytes(32), vrf_requests=1, **ok)  # other randomness


def test_payouts_are_idempotent_and_verified() -> None:
    i = inputs()
    h = snapshot_hash(i)
    p = resolve_draw(i, h, RHO, vrf_requests=1)
    ok = {"claimed_winners": list(p.winners), "claimed_prizes": p.prizes,
          "claimed_rollover": p.rollover}  # fmt: skip
    sends = verified_draw_payouts(i, h, RHO, vrf_requests=1, epoch=3, done_keys=(),
                                  onchain_memos=(), **ok)  # fmt: skip
    assert sum(s.amount for s in sends) == sum(p.prizes.values())
    assert sum(wallet_prizes(i, p).values()) == sum(p.prizes.values())
    done = {sends[0].key}
    onchain = {sends[1].key}
    again = verified_draw_payouts(i, h, RHO, vrf_requests=1, epoch=3, done_keys=done,
                                  onchain_memos=onchain, **ok)  # fmt: skip
    assert {s.key for s in again} == {s.key for s in sends} - done - onchain
    with pytest.raises(UnresolvedIntent):
        pending_sends({"w": 5}, epoch=3, draw=42, done_keys=(), onchain_memos=(),
                      open_intents={payment_key(3, 42, "w")})  # fmt: skip
    tampered = dict(ok, claimed_rollover=p.rollover + 1)
    with pytest.raises(DrawMismatch):
        verified_draw_payouts(i, h, RHO, vrf_requests=1, epoch=3, done_keys=(),
                              onchain_memos=(), **tampered)  # fmt: skip


def test_cli_verifier_exit_codes(tmp_path: Path) -> None:
    i = inputs()
    h = snapshot_hash(i)
    p = resolve_draw(i, h, RHO, vrf_requests=1)
    rec = {
        "commit": json.loads(i.canonical()),
        "snapshot_hash": h.hex(),
        "rho": RHO.hex(),
        "vrf_requests": 1,
        "claimed": {
            "winners": list(p.winners),
            "prizes": _canon(p.prizes),
            "rollover": str(p.rollover),
        },  # fmt: skip
    }
    f = tmp_path / "draw.json"
    f.write_text(json.dumps(rec))
    run = [sys.executable, str(ROOT / "tools" / "draw_verify.py"), str(f)]
    assert subprocess.run(run, capture_output=True).returncode == 0
    rec["claimed"]["rollover"] = str(p.rollover + 1)
    f.write_text(json.dumps(rec))
    assert subprocess.run(run, capture_output=True).returncode == 1
