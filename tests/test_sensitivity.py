"""OFAT sensitivity of §14 epoch_runner rows (cap, alpha, H, M)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine.params import CoinParams
from sim.epoch_runner import scenario_honest, scenario_whale_cap
from sim.sensitivity import (
    REPRO,
    render_report,
    run_cell,
    run_sweep,
    with_override,
    write_report,
)

_REPO = Path(__file__).resolve().parent.parent
_COMMITTED = _REPO / "reports" / "epoch_sensitivity.md"


def _canonical(text: str) -> str:
    return re.sub(r"Wall time: [0-9.]+s", "Wall time: Xs", text)


def test_with_override_sets_one_field_and_leaves_defaults_alone() -> None:
    base = CoinParams()
    assert base.scoring.cap == 0.05
    cap = with_override("cap", 0.03)
    assert cap.scoring.cap == 0.03
    assert cap.rewards.alpha_per_day == base.rewards.alpha_per_day
    assert cap.hold.horizon_days == base.hold.horizon_days
    assert cap.vesting.m == base.vesting.m
    assert CoinParams().scoring.cap == 0.05
    assert with_override("alpha", 0.20).rewards.alpha_per_day == 0.20
    assert with_override("H", 14).hold.horizon_days == 14
    assert with_override("M", 8).vesting.m == 8
    with pytest.raises(ValueError, match="unknown axis"):
        with_override("nope", 1)


def test_scenarios_honor_injected_cap() -> None:
    tight = with_override("cap", 0.03)
    whale = scenario_whale_cap(0, tight)
    assert whale.passed
    assert "max_pi=0.030000" in whale.evidence
    assert whale.margin == pytest.approx(0.0, abs=1e-12)
    honest = scenario_honest(0, tight)
    assert honest.passed
    assert honest.margin == pytest.approx(0.0, abs=1e-12)
    # default path still uses 0.05
    default = scenario_whale_cap(0)
    assert "max_pi=0.050000" in default.evidence


def test_flag_skips_cap_binding_zero_slack() -> None:
    cell = run_cell("cap", 0.05, "whale_cap", scenario_whale_cap, seeds=1)
    assert cell.passed and cell.cap_binds
    assert cell.margin == pytest.approx(0.0, abs=1e-12)
    assert not cell.flagged


def test_committed_report_matches_renderer_and_states_repro() -> None:
    cells = run_sweep(5)
    text = render_report(cells, elapsed=0.0, seeds=5)
    assert REPRO in text
    assert "Defaults are not changed" in text or "Defaults are not\nchanged" in text
    assert "Proposal: none" in text
    assert "scoring.cap" in text and "rewards.alpha_per_day" in text
    assert "hold.horizon_days" in text and "vesting.m" in text
    assert all(c.passed for c in cells)
    committed = _COMMITTED.read_text(encoding="utf-8")
    assert REPRO in committed
    assert "Proposal: none." in committed
    assert _canonical(committed) == _canonical(text)


def test_write_report_tmp(tmp_path: Path) -> None:
    dest, cells, elapsed = write_report(tmp_path / "out.md", seeds=1)
    assert dest.is_file() and elapsed >= 0 and all(c.passed for c in cells)
    body = dest.read_text(encoding="utf-8")
    assert REPRO in body and "| PASS |" in body
