"""Full-epoch sim e2e on run_epoch (ENGINE_DESIGN §8 / COIN_MATH §14)."""

from __future__ import annotations

from pathlib import Path

from engine.epoch import empty_state
from engine.params import CoinParams
from sim.agents import Holder
from sim.epoch_runner import (
    INFLOW,
    SCENARIOS,
    conservation_holds,
    inputs_from_world,
    render_table,
    run_e2e,
    run_slice,
    write_report,
)
from sim.run import main as run_main
from sim.world import run_world

_REPO = Path(__file__).resolve().parent.parent
_REPORT = _REPO / "reports" / "sim_epoch_e2e.md"


def test_conservation_and_inputs_window() -> None:
    world = run_world(0, 24 * 60, [Holder("h", "f", 10**9, 0)])
    inp = inputs_from_world(world, 0, 86_400, INFLOW)
    assert inp.t1 - inp.t0 == 86_400
    assert all(ev.ts < inp.t1 for ev in inp.events)
    assert inp.decimals == 9 and inp.pot_inflow == INFLOW
    result, nxt = run_slice(world, 0, 86_400, CoinParams())
    assert conservation_holds(empty_state(), INFLOW, result, nxt)


def test_all_scenarios_pass_on_seed_zero() -> None:
    for name, fn in SCENARIOS:
        row = fn(0)
        assert row.passed, f"{name} failed: {row.evidence}"


def test_e2e_ten_seeds_under_60s_and_committed_report(tmp_path: Path) -> None:
    rows, elapsed = run_e2e(10)
    assert elapsed < 60
    assert all(row.passed for row in rows)
    assert {row.name for row in rows} == {name for name, _fn in SCENARIOS}
    text = _REPORT.read_text(encoding="utf-8")
    assert "All rows passed." in text
    for name, _fn in SCENARIOS:
        assert f"| {name} |" in text and "| PASS |" in text
    # Regenerating into tmp is deterministic on pass/fail (elapsed may differ).
    dest, rows2, _e = write_report(tmp_path / "out.md", seeds=2)
    assert dest.is_file() and all(r.passed for r in rows2)


def test_run_e2e_flag(tmp_path: Path) -> None:
    out = tmp_path / "e2e.md"
    assert run_main(["--e2e", "--seeds", "1", "--out", str(out)]) == 0
    assert out.is_file() and "PASS" in out.read_text(encoding="utf-8")
    # --scenario still required when --e2e is off
    try:
        run_main(["--seeds", "1", "--out", str(tmp_path)])
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "--scenario" in str(exc) or exc.code not in (0, None)


def test_render_table_marks_failures() -> None:
    from sim.epoch_runner import Row

    text = render_table([Row("x", "cond", False, "numbers 1.23")], elapsed=0.5, seeds=1)
    assert "| FAIL |" in text and "**FAIL:** x" in text
