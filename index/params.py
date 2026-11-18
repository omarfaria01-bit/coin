"""Typed parameters for index/params.json (INDEX_RULES.md). Pure data, no I/O.

Unknown keys are rejected everywhere (extra="forbid"). Fractions are written as "num/den" strings.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FILTER_CODES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11")

Num = int | str


def frac(x: Num) -> Fraction:
    """Parse an int or an exact 'num/den' / integer string into a Fraction."""
    if isinstance(x, bool):
        raise ValueError("booleans are not numbers")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, str):
        try:
            return Fraction(x.strip())
        except ZeroDivisionError as e:
            raise ValueError(f"zero denominator: {x!r}") from e
    raise ValueError(f"not an exact number: {x!r}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Keywords(_Strict):
    strong: tuple[str, ...]
    weak: tuple[str, ...] = ()

    @field_validator("strong", "weak")
    @classmethod
    def _non_empty_words(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not w.strip() for w in v):
            raise ValueError("empty keyword")
        return v


class Filters(_Strict):
    min_age_hours: Num = 6
    min_liquidity_usd: Num = 50_000
    top10_min_pct: Num = 13
    top10_max_pct: Num = 27
    min_total_fees_sol: Num = 10
    max_bundle_pct: Num = 10
    max_dev_pct: Num = 5
    max_creator_launches_7d: int = Field(3, ge=1)
    require_authorities_revoked: bool = True
    min_unique_traders: int = Field(200, ge=0)
    min_turnover: Num = "1/20"
    max_turnover: Num = 3
    max_mc_liquidity_ratio: Num = 100  # F11 (#167, D29)
    # F8c (#171, D32): Token-2022 mint extensions allowed (jsonParsed names); all others fail.
    token2022_allowed_extensions: tuple[str, ...] = (
        "metadataPointer",
        "tokenMetadata",
        "interestBearingConfig",
        "scaledUiAmountConfig",
    )

    @model_validator(mode="after")
    def _ranges(self) -> Filters:
        for name in (
            "min_age_hours",
            "min_liquidity_usd",
            "top10_min_pct",
            "top10_max_pct",
            "min_total_fees_sol",
            "max_bundle_pct",
            "max_dev_pct",
            "min_turnover",
            "max_turnover",
            "max_mc_liquidity_ratio",
        ):
            if frac(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        if not frac(self.top10_min_pct) < frac(self.top10_max_pct) <= 100:
            raise ValueError("need top10_min_pct < top10_max_pct <= 100")
        if not 0 < frac(self.min_turnover) < frac(self.max_turnover):
            raise ValueError("need 0 < min_turnover < max_turnover")
        if frac(self.max_mc_liquidity_ratio) <= 0:
            raise ValueError("max_mc_liquidity_ratio must be > 0")
        if frac(self.min_liquidity_usd) <= 0 or frac(self.min_total_fees_sol) <= 0:
            raise ValueError("liquidity and fee minimums must be > 0 (the score takes their log)")
        if self.min_unique_traders < 1:
            raise ValueError("min_unique_traders must be >= 1 (the score takes its log)")
        return self


class Score(_Strict):
    w_mc: Num = "2/5"
    w_liquidity: Num = "3/10"
    w_fees: Num = "1/5"
    w_traders: Num = "1/10"
    score_fees_window: Literal["window", "lifetime"] = "window"
    round_decimals: int = Field(12, ge=6, le=15)

    @model_validator(mode="after")
    def _sum_to_one(self) -> Score:
        ws = [frac(self.w_mc), frac(self.w_liquidity), frac(self.w_fees), frac(self.w_traders)]
        if any(w < 0 for w in ws) or sum(ws) != 1:
            raise ValueError("score weights must be >= 0 and sum to exactly 1")
        return self


class Membership(_Strict):
    size: int = Field(10, ge=1)
    enter_rank: int = Field(8, ge=1)
    exit_rank: int = Field(12, ge=1)

    @model_validator(mode="after")
    def _order(self) -> Membership:
        if not self.enter_rank <= self.size <= self.exit_rank:
            raise ValueError("need enter_rank <= size <= exit_rank")
        return self


class Emergency(_Strict):
    liquidity_drop_pct_1h: Num = 50


class Weights(_Strict):
    mode: Literal["equal", "score_capped"] = "equal"
    cap_pct: Num = 20

    @field_validator("cap_pct")
    @classmethod
    def _cap(cls, v: Num) -> Num:
        if not 0 < frac(v) <= 100:
            raise ValueError("cap_pct must be in (0, 100]")
        return v


class Prize(_Strict):
    slippage_bps: int = Field(300, ge=0, le=10_000)


class DryRun(_Strict):
    skip_filters: tuple[str, ...] = ()

    @field_validator("skip_filters")
    @classmethod
    def _codes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = [c for c in v if c not in FILTER_CODES]
        if bad:
            raise ValueError(f"unknown filter codes: {bad}")
        return v


class Payout(_Strict):
    """This coin only. Engine `config/coin.json` is unchanged (D26)."""

    holder_rewards: Num = "7/10"
    draw_pot: Num = "3/10"
    team: Num = 0
    buyback_burn: Num = 0
    pay_in: Literal["basket"] = "basket"
    draw_period_hours: int = Field(1, ge=1)
    holder_reward_hours: int = Field(24, ge=1)
    min_prize_lamports: int = Field(10_000_000, ge=0)

    @model_validator(mode="after")
    def _sum(self) -> Payout:
        total = frac(self.holder_rewards) + frac(self.draw_pot)
        total += frac(self.team) + frac(self.buyback_burn)
        if total != 1:
            raise ValueError("payout shares must sum to 1")
        return self


class IndexParams(_Strict):
    version: str
    rebalance_hour_utc: int = Field(18, ge=0, le=23)
    rebalance_hours: int = Field(1, ge=1)
    window_hours: int = Field(24, ge=1)
    sample_minutes: int = Field(5, ge=1)
    holder_sample_minutes: int = Field(60, ge=1)
    min_coverage: Num = "1/2"
    keywords: Keywords
    filters: Filters = Filters()
    score: Score = Score()
    membership: Membership = Membership()
    emergency: Emergency = Emergency()
    weights: Weights = Weights()
    prize: Prize = Prize()
    payout: Payout = Payout()
    self_mint: str | None = None
    dry_run: DryRun = DryRun()

    @field_validator("min_coverage")
    @classmethod
    def _coverage(cls, v: Num) -> Num:
        if not 0 <= frac(v) <= 1:
            raise ValueError("min_coverage must be in [0, 1]")
        return v


class OverrideEntry(_Strict):
    mint: str
    reason: str = Field(min_length=3)
    issue: int = Field(ge=1, description="Issue where kiwi approved the entry")


class Overrides(_Strict):
    allow: tuple[OverrideEntry, ...] = ()
    deny: tuple[OverrideEntry, ...] = ()
