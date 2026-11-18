"""GTA 6 index: universe, filters, score and ranking (INDEX_RULES.md §1–§4). Pure: no I/O, no clock.

Floats are allowed here: the index never computes reward payouts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

import base58

from index.params import IndexParams, Overrides, frac


@dataclass(frozen=True)
class Metrics:
    """One candidate's measured values for the window (adapter output). None = missing."""

    mint: str
    ticker: str
    name: str = ""
    description: str = ""
    coverage: float | None = None  # share of the window covered by samples, 0..1
    age_hours: float | None = None
    liquidity_usd: float | None = None  # window average
    mc_usd: float | None = None  # window average
    top10_pct: float | None = None  # median of hourly samples, excl. vaults/burn/hubs
    total_fees_sol: float | None = None  # lifetime
    window_fees_sol: float | None = None
    bundle_pct: float | None = None
    dev_pct: float | None = None
    creator_launches_7d: int | None = None
    mint_authority_revoked: bool | None = None
    freeze_authority_revoked: bool | None = None
    token_program: str | None = None  # owner program of the mint account (F8c, #171)
    extensions: tuple[str, ...] | None = None  # Token-2022 mint extension names, () for legacy
    unique_traders: int | None = None
    volume_usd: float | None = None  # window total
    # D38: est. trading fees paid in 24h = DexScreener h24 volume (all pools) x dex_fee_rate, in SOL
    trading_fees_24h_sol: float | None = None
    # F9/F10 quality (#170, D33), from the swaps themselves
    independent_traders: int | None = None  # wallets above min_trader_volume_sol, no creator
    roundtrip_share: float | None = None  # share of SOL volume that is same-wallet round trips
    volume_wallets: int | None = None
    median_trade_sol: float | None = None
    sources: Mapping[str, str] = field(default_factory=dict)  # metric -> "<source>@<ISO time>"


# ------------------------------------------------------------------ §1 universe


def keyword_hit(text: str, keyword: str) -> bool:
    """True when `keyword` occurs in `text` with no letter touching it on either side."""
    kw = re.escape(" ".join(keyword.split()))
    kw = kw.replace(r"\ ", r"\s+")
    return re.search(rf"(?<![A-Za-z]){kw}(?![A-Za-z])", text, flags=re.IGNORECASE) is not None


def candidate_status(m: Metrics, params: IndexParams, overrides: Overrides) -> str | None:
    """None if `m` is a candidate, else why not: "self", "denied", "no_keyword"."""
    if params.self_mint is not None and m.mint == params.self_mint:
        return "self"
    if m.mint in {e.mint for e in overrides.deny}:
        return "denied"
    text = " ".join((m.name, m.ticker, m.description))
    if gta_match(text, params):
        return None
    return "no_keyword"


def gta_match(text: str, params: IndexParams) -> bool:
    """D37 vocabulary: a strong word, or an ambiguous word with GTA context (see Keywords)."""
    kw = params.keywords
    if any(keyword_hit(text, k) for k in kw.strong):
        return True
    hits = {k.lower() for k in kw.needs_context if keyword_hit(text, k)}
    generic = {k.lower() for k in kw.generic if keyword_hit(text, k)}
    return len(hits) >= 1 and len(hits | generic) >= 2  # D41: generic words never count alone


# ------------------------------------------------------------------ §3 filters

MISSING = "insufficient_data"
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

_NUMERIC = (
    "coverage",
    "age_hours",
    "liquidity_usd",
    "mc_usd",
    "top10_pct",
    "total_fees_sol",
    "window_fees_sol",
    "bundle_pct",
    "dev_pct",
    "volume_usd",
    "trading_fees_24h_sol",
    "roundtrip_share",
    "median_trade_sol",
)


def _all_finite(m: Metrics) -> bool:
    """NaN or infinity anywhere counts as missing data (fail-safe, never fail-open)."""
    return all(getattr(m, k) is None or math.isfinite(getattr(m, k)) for k in _NUMERIC)


def missing_metrics(m: Metrics, params: IndexParams) -> list[str]:
    """Names of the metrics that make `m` insufficient_data (published in the output, D37)."""
    skip = set(params.dry_run.skip_filters)
    out = [k for k in _NUMERIC if getattr(m, k) is not None and not math.isfinite(getattr(m, k))]
    if m.coverage is None or m.coverage <= 0:
        out.append("coverage(no samples)")
    need = {
        "F1": ("age_hours",),
        "F2": ("liquidity_usd",),
        "F3": ("top10_pct",),
        "F4": (
            "trading_fees_24h_sol"
            if params.filters.fees_measure == "dex_24h_trading"
            else "total_fees_sol",
        ),
        "F5": ("bundle_pct",),
        "F8": ("mint_authority_revoked", "freeze_authority_revoked", "token_program"),
        "F9": (
            "unique_traders"
            if params.filters.traders_measure == "window_wallets"
            else "independent_traders",
        ),
        "F10": ("volume_usd",),
        "F11": ("mc_usd",),
    }
    for code, names in need.items():
        if code in skip:
            continue
        out.extend(n for n in names if getattr(m, n) is None and n not in out)
    if m.token_program == TOKEN_2022 and m.extensions is None and "F8" not in skip:
        out.append("extensions")
    return out


def first_failed_filter(m: Metrics, params: IndexParams) -> str | None:
    """First failed filter ("F1".."F11" or "insufficient_data"), or None if all pass.

    A missing metric counts as a failure. Filters in `dry_run.skip_filters` are not checked.
    """
    f = params.filters
    skip = set(params.dry_run.skip_filters)
    if not _all_finite(m):
        return MISSING
    if m.coverage is None or m.coverage <= 0:  # D35: any samples count, none = no data
        return MISSING

    def lo(x: object) -> float:
        return float(frac(x))  # type: ignore[arg-type]

    if "F1" not in skip:
        if m.age_hours is None:
            return MISSING
        if m.age_hours < lo(f.min_age_hours):
            return "F1"
    if "F2" not in skip:
        if m.liquidity_usd is None:
            return MISSING
        if m.liquidity_usd < lo(f.min_liquidity_usd):
            return "F2"
    if "F3" not in skip:
        if m.top10_pct is None:
            return MISSING
        if not lo(f.top10_min_pct) <= m.top10_pct <= lo(f.top10_max_pct):
            return "F3"
    if "F4" not in skip:
        fees = m.trading_fees_24h_sol if f.fees_measure == "dex_24h_trading" else m.total_fees_sol
        if fees is None:
            return MISSING
        if fees < lo(f.min_total_fees_sol):
            return "F4"
    if "F5" not in skip:
        if m.bundle_pct is None:
            return MISSING
        if m.bundle_pct > lo(f.max_bundle_pct):
            return "F5"
    if "F8" not in skip and f.require_authorities_revoked:
        if m.mint_authority_revoked is None or m.freeze_authority_revoked is None:
            return MISSING
        if not (m.mint_authority_revoked and m.freeze_authority_revoked):
            return "F8"
    if "F8" not in skip:
        # F8c (#171, D32): legacy SPL, or Token-2022 with only allowlisted extensions. Fail-safe.
        if m.token_program is None:
            return MISSING
        if m.token_program == TOKEN_2022:
            if m.extensions is None:
                return MISSING
            if not set(m.extensions) <= set(f.token2022_allowed_extensions):
                return "F8"
        elif m.token_program != SPL_TOKEN:
            return "F8"
    if "F9" not in skip:
        window_wallets = f.traders_measure == "window_wallets"
        traders = m.unique_traders if window_wallets else m.independent_traders
        if traders is None:
            return MISSING
        if traders < f.min_unique_traders:
            return "F9"
    if "F10" not in skip:
        if m.volume_usd is None:
            return MISSING
        if m.volume_usd <= 0:  # D35: raw window volume as-is, only needs to exist
            return "F10"
    if "F11" not in skip:
        if m.mc_usd is None or m.liquidity_usd is None or m.liquidity_usd <= 0:
            return MISSING
        # Exact compare: mc <= ratio * liq. A thin pool cannot carry a huge market cap (#167).
        if Fraction(m.mc_usd) > frac(f.max_mc_liquidity_ratio) * Fraction(m.liquidity_usd):
            return "F11"
    return None


# ------------------------------------------------------------------ §4 score


def log_score(m: Metrics, params: IndexParams) -> float | None:
    """log S rounded to `round_decimals`; None if an input is missing or not > 0."""
    s = params.score
    if s.score_fees_window == "dex_24h":  # D38: same 24h all-pools measure as F4
        fees = m.trading_fees_24h_sol
    else:
        fees = m.window_fees_sol if s.score_fees_window == "window" else m.total_fees_sol
    vals = (m.mc_usd, m.liquidity_usd, fees, m.unique_traders)
    if any(v is None or not math.isfinite(v) or v <= 0 for v in vals):
        return None
    mc, liq, fe, tr = (float(v) for v in vals)  # type: ignore[arg-type]
    raw = (
        float(frac(s.w_mc)) * math.log(mc)
        + float(frac(s.w_liquidity)) * math.log(liq)
        + float(frac(s.w_fees)) * math.log(fe)
        + float(frac(s.w_traders)) * math.log(tr)
    )
    return round(raw, s.round_decimals)


def mint_key(mint: str) -> bytes:
    return base58.b58decode(mint)


def rank(scored: Mapping[str, float]) -> list[str]:
    """Mints by log S descending; ties by mint address bytes ascending. Rank 1 = index 0."""
    return sorted(scored, key=lambda mint: (-scored[mint], mint_key(mint)))
