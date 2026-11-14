"""Typed parameters for config/coin.json and config/pad.json (COIN_MATH v0.2).

Pure data models: no file or network I/O here. Loading lives in adapters/config_loader.py.
Unknown keys are rejected everywhere (extra="forbid").
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- coin.json


class EpochParams(_Strict):
    hours: int = Field(24, gt=0, description="Epoch length; epochs start at 00:00 UTC (§2)")


class EligibilityParams(_Strict):
    min_eligible_usd: float = Field(10.0, ge=0, description="B̄_c · TWAP_epoch threshold (§2)")
    min_hold_hours: float = Field(1.0, ge=0, description="Cluster must have held this long (§2)")


class HoldParams(_Strict):
    horizon_days: float = Field(30.0, gt=0, description="h(a)=1+min(1, ln(1+a)/ln(1+H)) (§3)")


class ChurnParams(_Strict):
    window_hours: float = Field(48.0, gt=0, description="Round-trip volume window (§4)")
    kappa: float = Field(2.0, ge=0, description="F = 1/(1+κχ) (§4)")


class UnderwaterParams(_Strict):
    twap_hours: float = Field(6.0, gt=0, description="P̃ window (§5)")
    min_age_hours: float = Field(48.0, ge=0, description="Only pool-buy lots this old count (§5)")
    beta: float = Field(0.5, ge=0, description="Max boost = 1+β (§5)")
    d_max: float = Field(0.75, gt=0, le=1, description="Drawdown that saturates the boost (§5)")


class ScoringParams(_Strict):
    cap: float = Field(0.05, gt=0, le=1, description="Whale cap on π_c (§6)")


class SybilWeights(_Strict):
    same_fee_payer: float = 1.0
    direct_transfer: float = 1.0
    same_first_funder: float = 1.0
    co_buy: float = 0.7
    identical_balances: float = 0.6


class SybilParams(_Strict):
    weights: SybilWeights = SybilWeights()
    strong_edge: float = Field(0.7, description="Union-find on edges with weight ≥ this (§7.1)")
    merge_threshold: float = Field(1.0, description="Merge weak pairs if summed evidence ≥ this")
    funder_window_hours: float = Field(72.0, gt=0)
    co_buy_slot_tolerance: int = Field(1, ge=0)
    co_buy_size_tolerance: float = Field(0.10, ge=0)
    co_buy_min_occurrences: int = Field(3, ge=1)
    identical_balance_tolerance: float = Field(0.001, ge=0)
    identical_balance_min_wallets: int = Field(4, ge=2)
    identical_balance_created_within_hours: float = Field(24.0, gt=0)
    review_cluster_size: int = Field(10, ge=2, description="Clusters this big go to review.csv")


class RewardParams(_Strict):
    enabled: bool = Field(True, description="Legal switch (§16)")
    alpha_per_day: float = Field(0.10, gt=0, le=1, description="R_e = α·Pot_e (§8)")
    min_epoch_payout_lamports: int = Field(
        10_000_000, ge=0, description="PROVISIONAL (0.01 SOL): skip epoch below this (§8)"
    )
    push_max_eligible: int = Field(
        500, ge=0, description="Below this, push instead of claims (§13)"
    )
    push_min_transfer_lamports: int = Field(
        1_000_000, ge=0, description="PROVISIONAL (0.001 SOL): smaller amounts carry forward (§13)"
    )
    lst_fraction: float = Field(
        0.0, ge=0, le=1, description="Share of idle pot held in an LST; 0 until decided (§8)"
    )


class DrawParams(_Strict):
    enabled: bool = Field(True, description="Legal switch (§16)")
    period_days: float = Field(7.0, gt=0)
    min_balance_usd: float = Field(10.0, ge=0, description="PROVISIONAL threshold (§9)")
    min_hold_hours: float = Field(24.0, ge=0)
    prize_split: tuple[float, ...] = Field(
        (0.40, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05),
        description="Share of the draw pot per rank (§9)",
    )

    @model_validator(mode="after")
    def _split_ok(self) -> DrawParams:
        if any(s <= 0 for s in self.prize_split):
            raise ValueError("prize_split entries must be > 0")
        if sum(self.prize_split) > 1 + 1e-12:
            raise ValueError("prize_split must sum to ≤ 1")
        return self


class FeeParams(_Strict):
    dev: float = Field(0.25, ge=0, le=1)
    holder_pot: float = Field(0.35, ge=0, le=1)
    draw_pot: float = Field(0.25, ge=0, le=1)
    buyback_burn: float = Field(0.15, ge=0, le=1)
    router_interval_minutes: int = Field(60, gt=0)

    @model_validator(mode="after")
    def _sum_one(self) -> FeeParams:
        total = self.dev + self.holder_pot + self.draw_pot + self.buyback_burn
        if not math.isclose(total, 1.0, abs_tol=1e-12):
            raise ValueError(f"fee shares must sum to 1, got {total}")
        return self


class VestingParams(_Strict):
    t_early_minutes: float = Field(15.0, ge=0, description="Early-buy window (§11)")
    mc_early_usd: float | None = Field(None, description="Or until MC ≥ this; None = time only")
    t_v_days: float = Field(7.0, gt=0)
    m: float = Field(5.0, gt=1, description="Full unlock at M× entry (§11)")
    unlock_twap_hours: float = Field(24.0, gt=0, description="UNLOCK_TWAP_H (§11)")
    forfeit_days: float = Field(30.0, ge=0, description="Soft-mode forfeit duration (§11B)")


class TreasuryBotParams(_Strict):
    mode: Literal["paper", "devnet", "live"] = "paper"
    seed_lamports: int | None = Field(None, description="TREASURY_SEED_SOL, set by kiwi (§12)")
    ema_halflife_hours: float = 6.0
    var_halflife_hours: float = 24.0
    f0: float = 0.5
    gamma: float = 0.15
    f_min: float = 0.1
    f_max: float = 0.9
    band: float = 0.05
    max_pool_volume_fraction: float = Field(0.02, gt=0, le=1)
    max_trade_lamports: int | None = None
    no_trade_first_hours: float = 24.0
    breaker_drawdown: float = Field(
        0.60, gt=0, lt=1, description="Stop buying at −60% from 7d high"
    )
    min_liquidity_lamports: int | None = Field(None, description="L_MIN")
    daily_loss_limit_lamports: int | None = None
    quiet_minutes: float = Field(15.0, ge=0, description="BOT_QUIET_MIN around buyback/payout")
    sweep_fraction: float = Field(0.5, ge=0, le=1, description="Weekly share of profit over HWM")

    @model_validator(mode="after")
    def _bounds(self) -> TreasuryBotParams:
        if not (0 <= self.f_min <= self.f0 <= self.f_max <= 1):
            raise ValueError("need 0 ≤ f_min ≤ f0 ≤ f_max ≤ 1")
        if self.mode == "live":
            raise ValueError("live mode is never set in the committed config (needs kiwi APPROVED)")
        return self


class CoinParams(_Strict):
    version: Literal["0.2"] = "0.2"
    epoch: EpochParams = EpochParams()
    eligibility: EligibilityParams = EligibilityParams()
    hold: HoldParams = HoldParams()
    churn: ChurnParams = ChurnParams()
    underwater: UnderwaterParams = UnderwaterParams()
    scoring: ScoringParams = ScoringParams()
    sybil: SybilParams = SybilParams()
    rewards: RewardParams = RewardParams()
    draws: DrawParams = DrawParams()
    fees: FeeParams = FeeParams()
    vesting: VestingParams = VestingParams()
    treasury_bot: TreasuryBotParams = TreasuryBotParams()


# ---------------------------------------------------------------- pad.json


class PadCurve(_Strict):
    type: str | None = None
    graduation_mc: float | None = None
    venue_after: str | None = None


class PadCreatorFee(_Strict):
    bps: int | None = Field(None, ge=0, le=10_000)
    recipient: str | None = None
    claim_method: str | None = None


class PadDevBuy(_Strict):
    max_pct: float | None = Field(None, ge=0, le=100)
    lockable: bool | None = None


class PadParams(_Strict):
    """Filled on launch day from the pad's public docs (§15); each field needs a source."""

    name: str | None = None
    program_ids: tuple[str, ...] = ()
    token_program: Literal["spl", "token2022"] | None = None
    curve: PadCurve = PadCurve()
    creator_fee: PadCreatorFee = PadCreatorFee()
    vesting_mode: Literal["native", "soft"] | None = None
    native_vesting_params_map: dict[str, str] = Field(default_factory=dict)
    dev_buy: PadDevBuy = PadDevBuy()
    anti_snipe: str | None = None
    transfer_hook_allowed: bool | None = None
    docs_url: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
