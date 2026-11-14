"""Pot smoothing, whale cap water-filling, payouts (COIN_MATH §6, §8). Owner: Grok."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_DOWN, Decimal, localcontext

from engine.types import ClusterId, WalletId

_DEC_PREC = 80


def _floor_prod(integer: int, factor: Decimal) -> int:
    """floor(integer · factor) with a wide Decimal context (int money must not drift)."""
    with localcontext() as ctx:
        ctx.prec = _DEC_PREC
        raw = (Decimal(integer) * factor).to_integral_value(rounding=ROUND_DOWN)
    return int(raw)


def epoch_budget(pot_lamports: int, alpha_per_day: float, epoch_hours: int) -> int:
    """R_e = floor(α_epoch · pot), α_epoch derived from α_per_day for the epoch length."""
    if pot_lamports < 0:
        raise ValueError(f"pot must be >= 0, got {pot_lamports}")
    with localcontext() as ctx:
        ctx.prec = _DEC_PREC
        alpha = Decimal(str(alpha_per_day))
        alpha_e = 1 - (1 - alpha) ** (Decimal(epoch_hours) / Decimal(24))
        payout = _floor_prod(pot_lamports, alpha_e)
    return min(pot_lamports, payout)


def capped_shares(scores: Mapping[ClusterId, float], cap: float) -> dict[ClusterId, float]:
    """Water-filling: shares ∝ score, each ≤ cap, Σ ≤ 1 (< 1 only when N < 1/cap).

    Terminates in ≤ N iterations. Zero/negative scores get 0.
    """
    if cap <= 0:
        raise ValueError(f"cap must be > 0, got {cap}")
    ids = sorted(scores)
    out = {cid: 0.0 for cid in ids}
    free = [cid for cid in ids if scores[cid] > 0]
    if not free:
        return out
    mass = 1.0
    max_iter = len(free)
    for _ in range(max_iter):
        total = sum(scores[cid] for cid in free)
        trial = {cid: mass * scores[cid] / total for cid in free}
        overflow = [cid for cid in free if trial[cid] >= cap]
        if not overflow:
            for cid, share in trial.items():
                out[cid] = share
            break
        for cid in overflow:
            out[cid] = cap
        overflow_set = set(overflow)
        free = [cid for cid in free if cid not in overflow_set]
        mass -= cap * len(overflow)
        if not free or mass <= 0:
            break
    else:
        raise ValueError("capped_shares exceeded N iterations")
    return {cid: min(share, cap) for cid, share in out.items()}


def allocate(budget: int, shares: Mapping[ClusterId, float]) -> tuple[dict[ClusterId, int], int]:
    """Floor each payout; return (payouts, rollover) with Σ payouts + rollover == budget."""
    if budget < 0:
        raise ValueError(f"budget must be >= 0, got {budget}")
    payouts: dict[ClusterId, int] = {}
    paid = 0
    for cid in sorted(shares):
        amt = _floor_prod(budget, Decimal(str(shares[cid])))
        payouts[cid] = amt
        paid += amt
    rollover = budget - paid
    assert rollover >= 0
    return payouts, rollover


def split_to_wallets(
    payout: int, weights: Mapping[WalletId, float]
) -> tuple[dict[WalletId, int], int]:
    """Per-wallet split ∝ B̄_w·H_w (§6); floor per wallet; return (amounts, dust)."""
    if payout < 0:
        raise ValueError(f"payout must be >= 0, got {payout}")
    amounts = {wid: 0 for wid in sorted(weights)}
    positive = [wid for wid in amounts if weights[wid] > 0]
    total_w = sum(weights[wid] for wid in positive)
    if total_w <= 0:
        return amounts, payout
    paid = 0
    for wid in amounts:
        if weights[wid] > 0:
            frac = Decimal(str(weights[wid])) / Decimal(str(total_w))
            amt = _floor_prod(payout, frac)
            amounts[wid] = amt
            paid += amt
    dust = payout - paid
    assert dust >= 0
    return amounts, dust
