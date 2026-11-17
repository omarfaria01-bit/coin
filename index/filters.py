"""GTA 6 index: universe, filters, score and ranking (INDEX_RULES.md §1–§4). Pure: no I/O, no clock.

Floats are allowed here: the index never computes reward payouts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

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
    unique_traders: int | None = None
    volume_usd: float | None = None  # window total
    sources: Mapping[str, str] = field(default_factory=dict)


# ------------------------------------------------------------------ §1 universe


def keyword_hit(text: str, keyword: str) -> bool:
    """True when `keyword` occurs in `text` with no letter touching it on either side."""
    kw = re.escape(" ".join(keyword.split()))
    kw = kw.replace(r"\ ", r"\s+")
    return re.search(rf"(?<![A-Za-z]){kw}(?![A-Za-z])", text, flags=re.IGNORECASE) is not None


def candidate_status(m: Metrics, params: IndexParams, overrides: Overrides) -> str | None:
    """None if `m` is a candidate, else why not: "self", "denied", "weak_keyword", "no_keyword".

    "weak_keyword" coins are listed in the output so kiwi can approve them with an allow entry.
    """
    if params.self_mint is not None and m.mint == params.self_mint:
        return "self"
    if m.mint in {e.mint for e in overrides.deny}:
        return "denied"
    if m.mint in {e.mint for e in overrides.allow}:
        return None
    text = " ".join((m.name, m.ticker, m.description))
    if any(keyword_hit(text, k) for k in params.keywords.strong):
        return None
    if any(keyword_hit(text, k) for k in params.keywords.weak):
        return "weak_keyword"
    return "no_keyword"


# ------------------------------------------------------------------ §3 filters

MISSING = "insufficient_data"


def first_failed_filter(m: Metrics, params: IndexParams) -> str | None:
    """First failed filter ("F1".."F10" or "insufficient_data"), or None if all pass.

    A missing metric counts as a failure. Filters in `dry_run.skip_filters` are not checked.
    """
    f = params.filters
    skip = set(params.dry_run.skip_filters)
    if m.coverage is None or m.coverage < float(frac(params.min_coverage)):
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
        if m.total_fees_sol is None:
            return MISSING
        if m.total_fees_sol < lo(f.min_total_fees_sol):
            return "F4"
    if "F5" not in skip:
        if m.bundle_pct is None:
            return MISSING
        if m.bundle_pct > lo(f.max_bundle_pct):
            return "F5"
    if "F6" not in skip:
        if m.dev_pct is None:
            return MISSING
        if m.dev_pct > lo(f.max_dev_pct):
            return "F6"
    if "F7" not in skip:
        if m.creator_launches_7d is None:
            return MISSING
        if m.creator_launches_7d > f.max_creator_launches_7d:
            return "F7"
    if "F8" not in skip and f.require_authorities_revoked:
        if m.mint_authority_revoked is None or m.freeze_authority_revoked is None:
            return MISSING
        if not (m.mint_authority_revoked and m.freeze_authority_revoked):
            return "F8"
    if "F9" not in skip:
        if m.unique_traders is None:
            return MISSING
        if m.unique_traders < f.min_unique_traders:
            return "F9"
    if "F10" not in skip:
        if m.volume_usd is None or m.mc_usd is None or m.mc_usd <= 0:
            return MISSING
        if not lo(f.min_turnover) <= m.volume_usd / m.mc_usd <= lo(f.max_turnover):
            return "F10"
    return None


# ------------------------------------------------------------------ §4 score


def log_score(m: Metrics, params: IndexParams) -> float | None:
    """log S rounded to `round_decimals`; None if an input is missing or not > 0."""
    s = params.score
    fees = m.window_fees_sol if s.score_fees_window == "window" else m.total_fees_sol
    vals = (m.mc_usd, m.liquidity_usd, fees, m.unique_traders)
    if any(v is None or v <= 0 for v in vals):
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
