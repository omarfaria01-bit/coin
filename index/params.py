"""Typed parameters for index/params.json (INDEX_RULES.md). Pure data, no I/O.

Unknown keys are rejected everywhere (extra="forbid"). Fractions are written as "num/den" strings.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FILTER_CODES = ("F1", "F2", "F3", "F4", "F5", "F8", "F9", "F10", "F11")  # F6 D35, F7 D38

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
    """One GTA vocabulary (D35, D37). Any `strong` word makes a coin a candidate.

    `needs_context` words are ambiguous outside GTA (Jason, Vice, Trevor...): they count only when
    the same name/ticker/description also has a strong word or a second, different
    `needs_context` word (GTA context). This is not a weaker tier: a match is a full candidate.
    """

    strong: tuple[str, ...]
    needs_context: tuple[str, ...] = ()

    @field_validator("strong", "needs_context")
    @classmethod
    def _non_empty_words(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not w.strip() for w in v):
            raise ValueError("empty keyword")
        return v


class Filters(_Strict):
    min_age_hours: Num = 4
    min_liquidity_usd: Num = 50_000
    top10_min_pct: Num = 0  # D38: no minimum
    top10_max_pct: Num = 30  # D38: kiwi 18 Nov 12:34
    min_total_fees_sol: Num = 8
    max_bundle_pct: Num = 30
    require_authorities_revoked: bool = True
    min_unique_traders: int = Field(200, ge=0)
    # F9 (D33): a trader needs this much SOL volume to count. F10 is volume > 0 (D35).
    min_trader_volume_sol: Num = "1/20"
    max_mc_liquidity_ratio: Num = 100  # F11 (#167, D29)
    # D38 (calibrated on kiwi's reference coins): how F4 and F9 are measured.
    # F4 "lifetime_network": tx+priority+tips since launch (needs the whole history).
    # F4 "dex_24h_trading": DexScreener h24 volume of all pools x dex_fee_rate, in SOL.
    fees_measure: Literal["lifetime_network", "dex_24h_trading"] = "lifetime_network"
    dex_fee_rate: Num = "1/400"
    # F9 "independent": wallets >= min_trader_volume_sol in the window (D33).
    # F9 "window_wallets": distinct fee payers of the window's swaps (lower bound if capped).
    traders_measure: Literal["independent", "window_wallets"] = "independent"
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
            "max_mc_liquidity_ratio",
            "min_trader_volume_sol",
        ):
            if frac(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        if not frac(self.top10_min_pct) < frac(self.top10_max_pct) <= 100:
            raise ValueError("need top10_min_pct < top10_max_pct <= 100")
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
    score_fees_window: Literal["window", "lifetime", "dex_24h"] = "window"  # dex_24h: D38
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
    confirm_gap_s: int = 900  # previous sample the drop must also show on (#172)


class Weights(_Strict):
    mode: Literal["equal", "score_capped", "mc_volume_capped", "sqrt_mc_capped"] = (
        "sqrt_mc_capped"  # D40
    )
    cap_pct: Num = 18
    floor_pct: Num = 0  # D40: per-member minimum (sqrt_mc_capped only)

    @field_validator("cap_pct")
    @classmethod
    def _cap(cls, v: Num) -> Num:
        if not 0 < frac(v) <= 100:
            raise ValueError("cap_pct must be in (0, 100]")
        return v

    @field_validator("floor_pct")
    @classmethod
    def _floor(cls, v: Num) -> Num:
        if not 0 <= frac(v) < 100:
            raise ValueError("floor_pct must be in [0, 100)")
        return v

    @model_validator(mode="after")
    def _floor_below_cap(self) -> Weights:
        if frac(self.floor_pct) > frac(self.cap_pct):
            raise ValueError("floor_pct must be <= cap_pct")
        return self


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


class Discovery(_Strict):
    """D37: top-down discovery from DexScreener search, by market cap, never new launches."""

    search_terms: tuple[str, ...] = ("GTA", "GTA 6", "GTA VI", "Vice City", "Leonida")
    max_by_mc: int = Field(40, ge=1)  # most established first
    max_trending: int = Field(10, ge=0)  # plus the top h24-volume coins, measured first
    # Hourly speed: a coin whose best DexScreener pool has less than this share of F2's minimum
    # is not walked on chain; it is listed as F2 from DexScreener alone.
    prescreen_liquidity_share: Num = "1/2"


class IndexParams(_Strict):
    version: str
    rebalance_hour_utc: int = Field(18, ge=0, le=23)
    rebalance_hours: int = Field(1, ge=1)
    window_hours: int = Field(24, ge=1)
    sample_minutes: int = Field(5, ge=1)
    holder_sample_minutes: int = Field(60, ge=1)
    keywords: Keywords
    discovery: Discovery = Discovery()
    filters: Filters = Filters()
    score: Score = Score()
    membership: Membership = Membership()
    emergency: Emergency = Emergency()
    weights: Weights = Weights()
    prize: Prize = Prize()
    payout: Payout = Payout()
    self_mint: str | None = None
    dry_run: DryRun = DryRun()


class OverrideEntry(_Strict):
    mint: str
    reason: str = Field(min_length=3)
    issue: int = Field(ge=1, description="Issue where kiwi approved the entry")


class Overrides(_Strict):
    """Deny list for scams only (D35). The allow mechanism is gone."""

    deny: tuple[OverrideEntry, ...] = ()
