"""INDEX_RULES.md must state the same numbers as index/params.json (#257).

Each check looks only inside the matching section or filter-table row, never the whole file,
so a number that appears elsewhere cannot hide drift. Params are the truth (D35-D40); if this
fails, fix the doc wording, not the params (changing a default needs a DECISIONS entry).
"""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

import pytest

from index.params import IndexParams

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "INDEX_RULES.md").read_text(encoding="utf-8")
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))


def _section(num: int) -> str:
    m = re.search(rf"^## {num}\. .*?(?=^## \d+\. |\Z)", DOC, re.M | re.S)
    assert m, f"INDEX_RULES.md has no section {num}"
    return m.group(0)


def _row(code: str) -> str:
    m = re.search(rf"^\| {code} \|.*$", _section(3), re.M)
    assert m, f"filter table has no row {code}"
    return m.group(0)


def _money(n: int) -> str:
    return f"${n:,}"


def _pct(x: str) -> str:
    return f"{Fraction(x) * 100}%"


F = P.filters

ROW_CASES = [
    ("F1", rf"≥ {F.min_age_hours}h"),
    ("F2", re.escape(f"≥ {_money(F.min_liquidity_usd)}")),
    ("F3", rf"at most {F.top10_max_pct}%"),
    ("F4", rf"≥ {F.min_total_fees_sol} SOL"),
    ("F5", rf"≤ {F.max_bundle_pct}% of supply"),
    ("F9", rf"≥ \*\*{F.min_unique_traders}\*\* distinct wallets"),
    ("F11", rf"≤ {F.max_mc_liquidity_ratio} ×"),
]


@pytest.mark.parametrize(("code", "pattern"), ROW_CASES, ids=[c for c, _ in ROW_CASES])
def test_filter_row_matches_params(code: str, pattern: str) -> None:
    row = _row(code)
    assert re.search(pattern, row), f"{code} row does not say {pattern!r}:\n{row}"


def test_f3_has_no_minimum_when_param_is_zero() -> None:
    if F.top10_min_pct == 0:
        assert "no minimum" in _row("F3")


def test_f8_authorities_rule() -> None:
    if F.require_authorities_revoked:
        assert "revoked" in _row("F8")


def test_measurement_section() -> None:
    s = _section(2)
    assert f"`rebalance_hours` = {P.rebalance_hours}" in s
    assert f"the {P.window_hours} hours before" in s
    assert f"every {P.sample_minutes} minutes" in s


def test_score_weights() -> None:
    s = _section(4)
    sc = P.score
    terms = [
        (sc.w_mc, "MC"),
        (sc.w_liquidity, "Liquidity"),
        (sc.w_fees, "Fees"),
        (sc.w_traders, "Traders"),
    ]
    for w, name in terms:
        dec = f"{float(Fraction(w)):g}"
        assert f"{dec}·ln({name})" in s, f"score weight for {name} should be {dec}"
    assert f"rounded to {sc.round_decimals} decimals" in s


def test_membership_buffer() -> None:
    s = _section(5)
    m = P.membership
    for key, val in (("size", m.size), ("enter_rank", m.enter_rank), ("exit_rank", m.exit_rank)):
        assert f"`{key} = {val}`" in s, f"section 5 should say {key} = {val}"
    assert f"down ≥ {P.emergency.liquidity_drop_pct_1h}% within 1h" in s


def test_weights_default_mode_and_bounds() -> None:
    s = _section(6)
    w = P.weights
    default = re.search(r"^- `(\w+)` \(default", s, re.M)
    assert default, "section 6 names no default weights mode"
    assert default.group(1) == w.mode
    line = s[default.start() : s.index("\n", default.start())]
    assert f"`cap_pct` {w.cap_pct}" in line
    if w.floor_pct:
        assert f"`floor_pct` {w.floor_pct}" in line


def test_payout_split() -> None:
    s = _section(7)
    pay = P.payout
    assert f"{_pct(pay.holder_rewards)} holder rewards, {_pct(pay.draw_pot)} draw pot" in s
    if pay.team == 0:
        assert "No team share" in s
    assert f"{pay.min_reward_lamports:,} lamports" in s
    assert f"{pay.draw_min_pot_lamports / 1e9:g} SOL (`draw_min_pot_lamports`)" in s
    assert f"{pay.min_prize_lamports / 1e9:g} SOL)" in s
    assert f"{P.prize.slippage_bps / 100:g}% slippage cap" in s
    assert f"`draw_enabled` {str(pay.draw_enabled).lower()}" in s


def test_detects_drift() -> None:
    """Sanity: the row check fails when the doc and params disagree."""
    row = _row("F4")
    assert not re.search(rf"≥ {F.min_total_fees_sol + 1} SOL", row)
