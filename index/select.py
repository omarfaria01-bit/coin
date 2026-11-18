"""GTA 6 index: membership, weights, prize split and output (INDEX_RULES.md §5–§8).

Pure: no I/O, no clock. Floats are allowed (the index never computes reward payouts), but weights
(basis points) and prize splits (lamports) are integers, and the same inputs always give
byte-identical output.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict

from index.filters import (
    MISSING,
    Metrics,
    candidate_status,
    first_failed_filter,
    log_score,
    mint_key,
    missing_metrics,
    rank,
)
from index.params import IndexParams, Overrides, frac

BPS = 10_000


# ------------------------------------------------------------------ §5 membership


def select_members(ranked: Sequence[str], prev: Iterable[str], params: IndexParams) -> list[str]:
    """Buffer rule. Returns members in rank order."""
    mp = params.membership
    prev_set = set(prev)
    pos = {mint: i + 1 for i, mint in enumerate(ranked)}
    eligible = [
        mint
        for mint in ranked
        if pos[mint] <= mp.enter_rank or (mint in prev_set and pos[mint] <= mp.exit_rank)
    ]
    members = eligible[: mp.size]
    if len(members) < mp.size:
        chosen = set(members)
        for mint in ranked:
            if len(members) >= mp.size:
                break
            if mint not in chosen:
                members.append(mint)
                chosen.add(mint)
        members.sort(key=lambda mint: pos[mint])
    return members


def _dropped(pair: tuple[float | None, float | None], limit_pct: float) -> bool:
    now, ago = pair
    return now is not None and bool(ago) and (ago - now) / ago * 100 >= limit_pct


def emergency_reason(
    liquidity_now: float | None,
    liquidity_1h_ago: float | None,
    mint_authority_revoked: bool | None,
    freeze_authority_revoked: bool | None,
    rug_flag: bool,
    params: IndexParams,
    earlier: tuple[float | None, float | None] | None = None,
) -> str | None:
    """Reason to remove a member between rebalances (§5), or None.

    `earlier` = (liquidity then, liquidity 1h before then) at the previous sample
    (#172). When given, a liquidity drop must show on both samples; a single print
    or missing earlier data does not remove a member.
    """
    if rug_flag:
        return "rug_flag"
    if mint_authority_revoked is False or freeze_authority_revoked is False:
        return "authority_enabled"
    if liquidity_now is not None and liquidity_1h_ago:
        drop_pct = (liquidity_1h_ago - liquidity_now) / liquidity_1h_ago * 100
        limit = float(frac(params.emergency.liquidity_drop_pct_1h))
        if drop_pct >= limit and (earlier is None or _dropped(earlier, limit)):
            return "liquidity_drop"
    return None


# ------------------------------------------------------------------ §6 weights


def _largest_remainder(
    exact: Sequence[float], total: int, frozen: frozenset[int] = frozenset()
) -> list[int]:
    """Floor each value, then +1 to the largest remainders, skipping `frozen` indices.

    Ties go to the earlier index, i.e. the better rank.
    """
    floors = [math.floor(x) for x in exact]
    left = total - sum(floors)
    order = [
        i
        for i in sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
        if i not in frozen
    ]
    if not 0 <= left <= len(order):
        raise ValueError("weights do not sum to the total")
    for i in order[:left]:
        floors[i] += 1
    return floors


def _mc_volume_shares(
    members: Sequence[str], inputs: Mapping[str, tuple[float, float]]
) -> list[float]:
    """D36: 0.5 * MC_i / sum MC + 0.5 * Volume_i / sum Volume (a half with a zero sum is equal)."""
    n = len(members)
    out = [0.0] * n
    for k in (0, 1):
        vals = [max(float(inputs[m][k]), 0.0) for m in members]
        tot = sum(vals)
        for i, v in enumerate(vals):
            out[i] += 0.5 * (v / tot if tot > 0 else 1 / n)
    return out


def weights_bps(
    members: Sequence[str],
    log_s: Mapping[str, float],
    params: IndexParams,
    mc_volume: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, int]:
    """Integer basis points per member (members in rank order), summing to 10,000.

    `mc_volume` maps mint -> (window-average market cap, window volume); required by mode
    `mc_volume_capped` (D36).
    """
    n = len(members)
    if n == 0:
        return {}
    cap_bps = frac(params.weights.cap_pct) * 100  # exact, e.g. 2000
    cap = float(cap_bps) / BPS
    frozen: frozenset[int] = frozenset()
    if params.weights.mode == "equal" or n * cap_bps < BPS:
        exact = [BPS / n] * n
    else:
        if params.weights.mode == "mc_volume_capped":
            if mc_volume is None:
                raise ValueError("mc_volume_capped needs market cap and volume per member")
            raw = _mc_volume_shares(members, mc_volume)
        else:
            top = max(log_s[m] for m in members)
            raw = [math.exp(log_s[m] - top) for m in members]
        capped = [False] * n
        while True:
            free = [i for i in range(n) if not capped[i]]
            if not free:
                w = [cap] * n
                break
            budget = 1 - cap * (n - len(free))
            base = sum(raw[i] for i in free)
            # Free members all at zero raw weight (no market cap and no volume): share the
            # remaining budget equally instead of dividing by zero.
            w = [
                cap if capped[i] else (raw[i] / base if base > 0 else 1 / len(free)) * budget
                for i in range(n)
            ]
            over = [i for i in free if w[i] > cap]
            if not over:
                break
            for i in over:
                capped[i] = True
        frozen = frozenset(i for i in range(n) if capped[i])
        exact = [float(cap_bps) if capped[i] else w[i] * BPS for i in range(n)]
    bps = _largest_remainder(exact, BPS, frozen)
    return dict(zip(members, bps, strict=True))


# ------------------------------------------------------------------ §7 prize split


def split_prize(lamports: int, members: Sequence[str], bps: Mapping[str, int]) -> dict[str, int]:
    """Per-member lamports for a basket prize; the remainder goes to the rank-1 member."""
    if lamports < 0:
        raise ValueError("negative prize")
    if not members:
        if lamports:
            raise ValueError("a prize needs at least one member")
        return {}
    parts = {m: lamports * bps[m] // BPS for m in members}
    parts[members[0]] += lamports - sum(parts.values())
    return parts


# ------------------------------------------------------------------ §8 output


def canonical_json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_index(
    candidates: Sequence[Metrics],
    prev_members: Sequence[str],
    params: IndexParams,
    overrides: Overrides,
    as_of: str,
    code_commit: str,
    emergency: Sequence[Mapping[str, str]] = (),
) -> dict:
    """Compute one rebalance. `as_of` and `code_commit` are passed in (no clock, no git here)."""
    by_mint: dict[str, Metrics] = {}
    for m in candidates:
        if m.mint in by_mint:
            raise ValueError(f"duplicate mint {m.mint}")
        mint_key(m.mint)  # rejects invalid base58 early
        by_mint[m.mint] = m

    excluded: list[dict] = []
    status: dict[str, str] = {}
    scored: dict[str, float] = {}
    for mint in sorted(by_mint, key=mint_key):
        m = by_mint[mint]
        reason = candidate_status(m, params, overrides)
        if reason is None:
            reason = first_failed_filter(m, params)
        missing: list[str] = []
        if reason is None:
            ls = log_score(m, params)
            if ls is None:
                reason = MISSING
                missing = ["score_inputs"]
            else:
                scored[mint] = ls
        elif reason == MISSING:
            missing = missing_metrics(m, params) or ["unknown"]
            for tag in ("error", "onchain"):
                if tag in m.sources:
                    missing.insert(0, m.sources[tag].rsplit("@", 1)[0])
        if reason is not None:
            status[mint] = reason
            if reason != "no_keyword":
                row: dict = {"mint": mint, "ticker": m.ticker, "reason": reason}
                if missing:  # D37: never silent, name what was missing
                    row["missing"] = missing
                if m.mc_usd is not None and math.isfinite(m.mc_usd):
                    row["mc_usd"] = round(m.mc_usd, 2)
                excluded.append(row)

    ranked = rank(scored)
    pos = {mint: i + 1 for i, mint in enumerate(ranked)}
    members = select_members(ranked, prev_members, params)
    bps = weights_bps(members, scored, params, _mc_volume(by_mint, members))

    changes = {
        "entered": sorted(set(members) - set(prev_members), key=lambda x: pos[x]),
        "exited": [
            {
                "mint": mint,
                "reason": status.get(mint, f"rank_{pos[mint]}" if mint in pos else "not_measured"),
            }
            for mint in sorted(set(prev_members) - set(members), key=mint_key)
        ],
    }
    out = {
        "as_of": as_of,
        "code_commit": code_commit,
        "dry_run": bool(params.dry_run.skip_filters),
        "skipped_filters": sorted(params.dry_run.skip_filters, key=lambda c: int(c[1:])),
        "params_hash": sha256_hex(canonical_json(params.model_dump(mode="json"))),
        "inputs_hash": sha256_hex(
            canonical_json(
                {
                    "candidates": [
                        _metrics_json(by_mint[k]) for k in sorted(by_mint, key=mint_key)
                    ],
                    "prev_members": sorted(prev_members, key=mint_key),
                    "overrides": overrides.model_dump(mode="json"),
                }
            )
        ),
        "members": [
            {
                "mint": mint,
                "ticker": by_mint[mint].ticker,
                "rank": pos[mint],
                "log_s": scored[mint],
                "weight_bps": bps[mint],
                "metrics": _metrics_json(by_mint[mint]),
            }
            for mint in members
        ],
        "excluded": excluded,
        "changes": changes,
        "emergency": [dict(e) for e in emergency],
    }
    return out


def _mc_volume(
    by_mint: Mapping[str, Metrics], members: Sequence[str]
) -> dict[str, tuple[float, float]]:
    return {
        m: (float(by_mint[m].mc_usd or 0.0), float(by_mint[m].volume_usd or 0.0)) for m in members
    }


def mc_volume_of(items: Sequence[Mapping]) -> dict[str, tuple[float, float]]:
    """(mc, volume) per member from published member items (`metrics` dict); missing = 0."""
    return {
        it["mint"]: (
            float((it.get("metrics") or {}).get("mc_usd") or 0.0),
            float((it.get("metrics") or {}).get("volume_usd") or 0.0),
        )
        for it in items
    }


def _metrics_json(m: Metrics) -> dict:
    d = asdict(m)
    d["sources"] = dict(m.sources)
    return d
