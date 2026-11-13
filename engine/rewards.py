"""Pot smoothing, whale cap water-filling, payouts (COIN_MATH §6, §8). Owner: Claude."""

from __future__ import annotations

from collections.abc import Mapping

from engine.types import ClusterId, WalletId


def epoch_budget(pot_lamports: int, alpha_per_day: float, epoch_hours: int) -> int:
    """R_e = floor(α_epoch · pot), α_epoch derived from α_per_day for the epoch length."""
    raise NotImplementedError


def capped_shares(scores: Mapping[ClusterId, float], cap: float) -> dict[ClusterId, float]:
    """Water-filling: shares ∝ score, each ≤ cap, Σ ≤ 1 (< 1 only when N < 1/cap).

    Terminates in ≤ N iterations. Zero/negative scores get 0.
    """
    raise NotImplementedError


def allocate(budget: int, shares: Mapping[ClusterId, float]) -> tuple[dict[ClusterId, int], int]:
    """Floor each payout; return (payouts, rollover) with Σ payouts + rollover == budget."""
    raise NotImplementedError


def split_to_wallets(
    payout: int, weights: Mapping[WalletId, float]
) -> tuple[dict[WalletId, int], int]:
    """Per-wallet split ∝ B̄_w·H_w (§6); floor per wallet; return (amounts, dust)."""
    raise NotImplementedError
