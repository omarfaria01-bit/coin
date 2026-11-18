"""Draw commit → reveal (D39, audit #271 H3/M1). Pure: no I/O, no clock, no network.

Every input that can change a draw is hashed into one 32-byte `snapshot_hash` *before* any
randomness exists: the group scores and balances, their member wallets, the manual overrides,
the hub/exchange list, the excluded list, the event cut-off (slot and time), the pot, the prize
split and all draw params. The operator then

1. commits `snapshot_hash` on-chain (memo or account) and publishes the canonical JSON;
2. makes **exactly one** ORAO VRF request with seed = `snapshot_hash` (`vrf_seed`);
3. if the request fails or is not fulfilled by the deadline: **no retry**, the pot rolls over.

`resolve_draw` applies these rules; `verify_draw` (used by `tools/draw_verify.py` and by the
payout guard) recomputes everything from the public record and raises on any mismatch, so a
payout can never follow a draw that anyone else would compute differently.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from hashlib import sha256
from typing import Any

from engine.hourly_draw import DrawPlan, plan_hourly_draw
from engine.rewards import split_cluster_payout

COMMIT_PREFIX = b"GTASP10_DRAW_COMMIT_V1"


class DrawMismatch(ValueError):
    """The public record does not reproduce: never pay."""


def _canon(x: Any) -> Any:
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, int):
        return str(x)  # big ints exact, no JSON float rounding
    if isinstance(x, Fraction):
        return f"{x.numerator}/{x.denominator}"
    if isinstance(x, bytes):
        return x.hex()
    if isinstance(x, Mapping):
        return {str(k): _canon(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, list | tuple | set | frozenset):
        items = [_canon(v) for v in x]
        return sorted(items, key=json.dumps) if isinstance(x, set | frozenset) else items
    raise TypeError(f"cannot commit {type(x).__name__}")


@dataclass(frozen=True)
class DrawInputs:
    """Everything a draw depends on. Lists that are sets (hubs, excluded) are sorted on hash."""

    mint: bytes
    genesis_hash: bytes
    draw_index: int
    cutoff_slot: int
    cutoff_ts: int
    total_supply: int
    pot: int
    prize_bps: tuple[int, ...]
    scores: Mapping[str, Fraction]  # group id → score (lots ≥ T_START, COIN_MATH §3)
    balances: Mapping[str, Fraction]  # group id → balance used for the 5% cap / 0.01% minimum
    wallet_scores: Mapping[str, Mapping[str, Fraction]]  # group → wallet → part of the score
    overrides: tuple[tuple[str, str, str], ...] = ()  # S3 manual merges (a, b, id)
    hubs: frozenset[str] = frozenset()  # exchange / hub list
    excluded: frozenset[str] = frozenset()  # pools, PDAs, burn, dev, treasury
    params: Mapping[str, Any] = field(default_factory=dict)  # cap, supply_cap, min_*, code commit

    def canonical(self) -> bytes:
        body = {
            "v": 1,
            "mint": self.mint,
            "genesis_hash": self.genesis_hash,
            "draw_index": self.draw_index,
            "cutoff_slot": self.cutoff_slot,
            "cutoff_ts": self.cutoff_ts,
            "total_supply": self.total_supply,
            "pot": self.pot,
            "prize_bps": list(self.prize_bps),
            "scores": {k: Fraction(v) for k, v in self.scores.items()},
            "balances": {k: Fraction(v) for k, v in self.balances.items()},
            "wallet_scores": {
                g: {w: Fraction(s) for w, s in ws.items()} for g, ws in self.wallet_scores.items()
            },
            "overrides": sorted(list(o) for o in self.overrides),
            "hubs": frozenset(self.hubs),
            "excluded": frozenset(self.excluded),
            "params": dict(self.params),
        }
        return json.dumps(_canon(body), sort_keys=True, separators=(",", ":")).encode()


def _f(v: Any) -> Fraction:
    return Fraction(v) if not isinstance(v, str) else Fraction(*map(int, v.split("/")))


def inputs_from_public(body: Mapping[str, Any]) -> DrawInputs:
    """Inverse of `DrawInputs.canonical()` (the JSON the operator publishes before the VRF)."""
    if str(body.get("v")) != "1":
        raise ValueError("unknown commit version")
    return DrawInputs(
        mint=bytes.fromhex(body["mint"]),
        genesis_hash=bytes.fromhex(body["genesis_hash"]),
        draw_index=int(body["draw_index"]),
        cutoff_slot=int(body["cutoff_slot"]),
        cutoff_ts=int(body["cutoff_ts"]),
        total_supply=int(body["total_supply"]),
        pot=int(body["pot"]),
        prize_bps=tuple(int(b) for b in body["prize_bps"]),
        scores={k: _f(v) for k, v in body["scores"].items()},
        balances={k: _f(v) for k, v in body["balances"].items()},
        wallet_scores={
            g: {w: _f(s) for w, s in ws.items()} for g, ws in body["wallet_scores"].items()
        },
        overrides=tuple(tuple(o) for o in body.get("overrides", [])),  # type: ignore[misc]
        hubs=frozenset(body.get("hubs", [])),
        excluded=frozenset(body.get("excluded", [])),
        params=dict(body.get("params", {})),
    )


def snapshot_hash(inputs: DrawInputs) -> bytes:
    """sha256(prefix ‖ canonical JSON). Changing any input changes the hash."""
    return sha256(COMMIT_PREFIX + inputs.canonical()).digest()


def vrf_seed(commit: bytes) -> bytes:
    """ORAO request seed = the committed snapshot hash (one request per seed, by construction)."""
    if len(commit) != 32:
        raise ValueError("commit must be 32 bytes")
    return bytes(commit)


_PARAM_KEYS = ("cap", "supply_cap", "min_holding_share", "min_groups", "min_pot")


def _plan_kwargs(params: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _PARAM_KEYS:
        if k in params:
            v = params[k]
            out[k] = int(v) if k in ("min_groups", "min_pot") else Fraction(v)
    return out


def resolve_draw(
    inputs: DrawInputs,
    committed: bytes,
    rho: bytes | None,
    *,
    vrf_requests: int,
) -> DrawPlan:
    """Commit → reveal. Hash mismatch raises; anything but one fulfilled request rolls over."""
    if snapshot_hash(inputs) != committed:
        raise DrawMismatch("inputs do not match the committed snapshot hash")
    if vrf_requests != 1 or rho is None:
        reason = "vrf_retry_forbidden" if vrf_requests > 1 else "vrf_unfulfilled"
        return DrawPlan(False, (), {}, inputs.pot, reason)
    return plan_hourly_draw(
        inputs.scores,
        inputs.pot,
        inputs.prize_bps,
        balances=inputs.balances,
        total_supply=inputs.total_supply,
        genesis_hash=inputs.genesis_hash,
        mint=inputs.mint,
        draw_index=inputs.draw_index,
        snapshot_hash=committed,
        rho=rho,
        **_plan_kwargs(inputs.params),
    )


def wallet_prizes(inputs: DrawInputs, plan: DrawPlan) -> dict[str, int]:
    """Split each group's prize to its wallets by score part (COIN_MATH §6), Σ exact."""
    out: dict[str, int] = {}
    for group, amount in plan.prizes.items():
        parts = inputs.wallet_scores.get(group) or {group: Fraction(1)}
        for w, v in split_cluster_payout(amount, parts).items():
            if v:
                out[w] = out.get(w, 0) + v
    return dict(sorted(out.items()))


def verify_draw(
    inputs: DrawInputs,
    committed: bytes,
    rho: bytes | None,
    *,
    vrf_requests: int,
    claimed_winners: Sequence[str],
    claimed_prizes: Mapping[str, int],
    claimed_rollover: int,
) -> DrawPlan:
    """Recompute from public data; raise DrawMismatch unless winners, prizes, rollover all match."""
    plan = resolve_draw(inputs, committed, rho, vrf_requests=vrf_requests)
    got = (tuple(plan.winners), dict(plan.prizes), plan.rollover)
    want = (
        tuple(claimed_winners),
        {k: int(v) for k, v in claimed_prizes.items()},
        claimed_rollover,
    )
    if got != want:
        raise DrawMismatch(f"recomputed {got} != claimed {want}")
    return plan
