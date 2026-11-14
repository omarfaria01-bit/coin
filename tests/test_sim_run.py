"""sim.run exit codes (--strict) and the vesting TWAP sweep."""

from __future__ import annotations

from pathlib import Path

import pytest

from sim.run import exit_code, main
from sim.sweep import (
    K_VALUES,
    UNLOCK_LIMIT,
    render_report,
    smallest_safe_window,
    unlocked_for,
    write_report,
)

_REPO = Path(__file__).resolve().parent.parent
_COMMITTED = _REPO / "reports" / "vesting_twap_sweep.md"


def _registry(monkeypatch, name: str, fn) -> None:
    from sim import run as runmod
    from sim import scenarios

    monkeypatch.setitem(runmod.REGISTRY, name, fn)
    monkeypatch.setitem(scenarios.REGISTRY, name, fn)


def test_exit_code_non_strict_skipped_is_zero() -> None:
    payload = {"pass": "skipped", "runs": [{"pass": "skipped"}, {"pass": "skipped"}]}
    assert exit_code(payload, strict=False) == 0
    assert exit_code(payload, strict=True) == 1


def test_exit_code_strict_requires_every_seed() -> None:
    assert exit_code({"pass": True, "runs": []}, strict=True) == 1
    assert exit_code({"pass": True, "runs": [{"pass": True}]}, strict=True) == 0
    mixed = {"pass": False, "runs": [{"pass": True}, {"pass": "skipped"}]}
    assert exit_code(mixed, strict=True) == 1
    assert exit_code({"pass": False, "runs": [{"pass": False}]}, strict=False) == 1


def test_strict_cli_skipped_is_nonzero(tmp_path: Path, monkeypatch) -> None:
    _registry(monkeypatch, "dummy_skip", lambda seed: {"pass": "skipped", "reason": "x"})
    out = str(tmp_path)
    assert main(["--scenario", "dummy_skip", "--seeds", "2", "--out", out, "--strict"]) == 1
    assert main(["--scenario", "dummy_skip", "--seeds", "2", "--out", out]) == 0


def test_strict_cli_failure_and_success(tmp_path: Path, monkeypatch) -> None:
    _registry(
        monkeypatch,
        "dummy_mix",
        lambda seed: {"pass": True} if seed == 0 else {"pass": False},
    )
    _registry(monkeypatch, "dummy_ok", lambda seed: {"pass": True})
    out = str(tmp_path)
    assert main(["--scenario", "dummy_mix", "--seeds", "2", "--out", out, "--strict"]) == 1
    assert main(["--scenario", "dummy_ok", "--seeds", "3", "--out", out, "--strict"]) == 0


def test_sweep_k3_1h_24h_is_just_under_five_percent() -> None:
    got = unlocked_for(3.0, 1.0, 24)
    assert got == pytest.approx(0.0497, abs=1e-3)
    assert got < UNLOCK_LIMIT


def test_smallest_safe_window_1h_3_1_and_3_5() -> None:
    assert smallest_safe_window(3.0, 1.0) == 24
    assert smallest_safe_window(3.1, 1.0) == 36
    assert smallest_safe_window(3.5, 1.0) == 36
    assert unlocked_for(3.1, 1.0, 24) >= UNLOCK_LIMIT
    assert unlocked_for(3.5, 1.0, 24) >= UNLOCK_LIMIT


def test_committed_report_matches_renderer_and_states_windows() -> None:
    text = render_report()
    assert _COMMITTED.read_text(encoding="utf-8") == text
    # 1h / 24h / k=3 cell is the margin number, not bold (just under 5%).
    assert "| 3× | **0.1787** | **0.0958** | 0.0497 | 0.0336 |" in text
    assert "1h 3.1×: **36h**" in text
    assert "1h 3.5×: **36h**" in text
    # Marking is only on the 1h table: a 0.5h 3.1× / 12h cell is ≥5% but not bold.
    assert "## Pump duration 0.5h" in text
    section_05 = text.split("## Pump duration 0.5h", 1)[1].split("## Pump duration 1h", 1)[0]
    assert "**0.0521**" not in section_05
    assert "0.0521" in section_05


def test_write_report_is_byte_identical(tmp_path: Path) -> None:
    a = write_report(tmp_path / "a.md")
    b = write_report(tmp_path / "b.md")
    assert a.read_bytes() == b.read_bytes() == _COMMITTED.read_bytes()


def test_grid_covers_requested_axes() -> None:
    assert K_VALUES == (2.0, 2.5, 3.0, 3.1, 3.5, 4.0)
