"""COIN_MATH.md default constants must match engine/params.py (issue #151).

Each row pins (doc anchor, params value). The anchor is a literal snippet that must still
appear in COIN_MATH.md, so editing either side without the other fails CI.
Known drifts are listed in KNOWN_MISMATCHES (xfail strict): fixing one flips it to XPASS,
which fails, forcing the entry's removal. Never change a default here (needs DECISIONS + sim).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from engine.params import CoinParams

DOC = (Path(__file__).resolve().parent.parent / "COIN_MATH.md").read_text(encoding="utf-8")
P = CoinParams()
H = 3600
DAY = 86_400

# (doc anchor, params getter, expected value from the doc)
MATCHING = [
    ("`E = 86,400`", lambda: P.epoch.hours * H, DAY),
    (
        "default 1/1,000,000 of supply",
        lambda: parse(P.eligibility.min_eligible_share),
        Fraction(1, 10**6),
    ),
    ("`T_START` = 6 hours", lambda: P.hold.t_start_seconds, 6 * H),
    ("split at 48h", lambda: P.hold.boost_age_seconds, 48 * H),
    ("β = 1/2, D_max = 3/4", lambda: (P.underwater.beta, P.underwater.d_max), (0.5, 0.75)),
    ("`CAP = 1/20`", lambda: P.scoring.cap, 0.05),
    ("α = 1/10 per day", lambda: P.rewards.alpha_per_day, 0.1),
    ("DRAW_PERIOD` = 7 epochs", lambda: P.draws.period_days, 7.0),
    (
        "1 × 40% of D,  3 × 10% of D,  6 × 5% of D",
        lambda: P.draws.prize_split,
        (0.40, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05),
    ),
    (
        "| Dev wallets (kiwi + Omega) | 25% |",
        lambda: (P.fees.dev, P.fees.holder_pot, P.fees.draw_pot, P.fees.buyback_burn),
        (0.25, 0.35, 0.25, 0.15),
    ),
    ("`T_EARLY` (default 15 min", lambda: P.vesting.t_early_minutes, 15.0),
    ("T_v = 7 days", lambda: P.vesting.t_v_days, 7.0),
    ("M = 5", lambda: P.vesting.m, 5.0),
    ("`tainted_until = t + 30 days`", lambda: P.vesting.forfeit_days, 30.0),
    ("`D_TRUST` (default 2 SOL)", lambda: P.prices.d_trust_lamports, 2_000_000_000),
    ("`MIN_PAYOUT_Q` (default 0.001 SOL", lambda: P.rewards.push_min_transfer_lamports, 1_000_000),
    ("Small holder count (< 500 eligible)", lambda: P.rewards.push_max_eligible, 500),
    ("half-life 6h", lambda: P.treasury_bot.ema_halflife_hours, 6.0),
    ("half-life 24h", lambda: P.treasury_bot.var_halflife_hours, 24.0),
    (
        "f0 = 0.5, γ = 0.15, f_min = 0.1, f_max = 0.9",
        lambda: (
            P.treasury_bot.f0,
            P.treasury_bot.gamma,
            P.treasury_bot.f_min,
            P.treasury_bot.f_max,
        ),
        (0.5, 0.15, 0.1, 0.9),
    ),
    ("trade only if |f − f*| > band (0.05)", lambda: P.treasury_bot.band, 0.05),
    ("2% of 1h pool volume", lambda: P.treasury_bot.max_pool_volume_fraction, 0.02),
    ("No trading in the first 24h", lambda: P.treasury_bot.no_trade_first_hours, 24.0),
    ("sweep 50% of (cumulative", lambda: P.treasury_bot.sweep_fraction, 0.5),
]

# Doc table row -> h in knots (age seconds, doc multiplier). Compared exactly.
DOC_KNOTS = [
    (2 * H, "1.00"), (6 * H, "1.15"), (12 * H, "1.30"), (DAY, "1.50"), (2 * DAY, "1.75"),
    (3 * DAY, "1.90"), (7 * DAY, "2.10"), (14 * DAY, "2.30"), (30 * DAY, "2.50"),
    (60 * DAY, "2.70"), (90 * DAY, "2.80"),
]  # fmt: skip

# Real drifts at time of writing (see PR body / follow-up issue). strict xfail.
KNOWN_MISMATCHES = [
    ("| Link | L4. Co-trades", lambda: P.sybil.weights.co_buy, 0.4),
    ("| Link | L5. Identical balances", lambda: P.sybil.weights.identical_balances, 0.3),
    ("get **no** link weight from it", lambda: P.sybil.weights.same_fee_payer, 0.0),
    ("MIN_DRAW_SHARE · total supply", lambda: P.draws.min_balance_usd, None),
]


def parse(text: str) -> Fraction:
    return Fraction(text)


@pytest.mark.parametrize(("anchor", "get", "expected"), MATCHING, ids=[m[0][:40] for m in MATCHING])
def test_doc_default_matches_params(anchor, get, expected):
    assert anchor in DOC, f"anchor vanished from COIN_MATH.md: {anchor!r}"
    got = get()
    if isinstance(expected, tuple) and all(isinstance(x, float) for x in expected):
        assert got == pytest.approx(expected)
    else:
        assert got == pytest.approx(expected) if isinstance(expected, float) else got == expected


def test_hold_knots_match_doc_table():
    row_age = "| age | < 6h | 2h | 6h | 12h | 24h | 48h | 72h | 7d | 14d | 30d | 60d | 90d+ |"
    row_h = "| h | 0 | 1.00 | 1.15 | 1.30 | 1.50 | 1.75 | 1.90 | 2.10 | 2.30 | 2.50 | 2.70 | 2.80 |"
    assert row_age in DOC
    assert row_h in DOC
    doc = tuple((a, Fraction(h)) for a, h in DOC_KNOTS)
    assert P.hold.knot_fractions() == doc


@pytest.mark.parametrize(
    ("anchor", "get", "expected"), KNOWN_MISMATCHES, ids=[m[0][:40] for m in KNOWN_MISMATCHES]
)
def test_known_mismatch_still_drifts(anchor, get, expected):
    """Documents drift. When params and doc agree, delete the row (strict)."""
    assert anchor in DOC, f"anchor vanished: {anchor!r}"
    assert get() != expected, f"drift fixed for {anchor!r}: remove it from KNOWN_MISMATCHES"
