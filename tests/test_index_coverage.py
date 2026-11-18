"""Coverage-time model tests (#215): monotonicity, edge cases and the generated table."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sim.index_coverage import hours_to_eligible, main

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "sim" / "index_coverage.py"
WINDOW = 24.0


def test_five_minute_sampler_needs_twelve_hours() -> None:
    # The current params (5-minute samples, min_coverage 1/2) against the 24 h window.
    assert hours_to_eligible(5, 0.0, 0.5) == 12.0


def test_missed_samples_stretch_the_time() -> None:
    assert hours_to_eligible(5, 0.10, 0.5) == pytest.approx(WINDOW * 0.5 / 0.9)
    assert hours_to_eligible(5, 0.30, 0.5) == pytest.approx(WINDOW * 0.5 / 0.7)


def test_slower_cadence_cannot_hold_a_five_minute_grid() -> None:
    # 10 min fills every other 5-minute bucket: exactly 50% at best, so only zero
    # misses can reach min_coverage, and then not before the whole window has run.
    assert hours_to_eligible(10, 0.0, 0.5) == WINDOW
    assert math.isinf(hours_to_eligible(10, 0.10, 0.5))
    # 15 min tops out at 1/3 of the buckets: never eligible at 50%.
    for missed in (0.0, 0.1, 0.3):
        assert math.isinf(hours_to_eligible(15, missed, 0.5))


def test_edge_miss_rate_zero_and_one() -> None:
    assert hours_to_eligible(5, 0.0, 0.0) == 0.0
    assert hours_to_eligible(5, 0.0, 1.0) == WINDOW
    assert math.isinf(hours_to_eligible(5, 1.0, 0.5))
    assert hours_to_eligible(5, 1.0, 0.0) == 0.0
    # A ceiling equals the target only at the boundary, never below it.
    assert math.isinf(hours_to_eligible(5, 0.2, 0.9))
    assert hours_to_eligible(5, 0.1, 0.9) == pytest.approx(WINDOW)


def test_faster_than_the_bucket_gets_several_ticks_per_bucket() -> None:
    assert hours_to_eligible(1, 0.0, 1.0) == WINDOW
    # A 5-minute bucket gets five 1-minute ticks; only all five missing leaves it empty.
    assert hours_to_eligible(1, 0.30, 0.5) == pytest.approx(WINDOW * 0.5 / (1 - 0.3**5))


@pytest.mark.parametrize(
    "override",
    [
        {"sample_minutes": 0},
        {"sample_minutes": -5},
        {"sample_minutes": True},
        {"sample_minutes": float("nan")},
        {"miss_rate": -0.1},
        {"miss_rate": 1.1},
        {"miss_rate": float("inf")},
        {"min_coverage": -0.01},
        {"min_coverage": 1.01},
        {"min_coverage": "1/2"},
        {"window_hours": 0},
        {"bucket_minutes": 0},
    ],
)
def test_rejects_bad_inputs(override: dict[str, object]) -> None:
    args: dict[str, object] = {"sample_minutes": 5, "miss_rate": 0.0, "min_coverage": 0.5}
    args.update(override)
    with pytest.raises(ValueError):
        hours_to_eligible(**args)  # type: ignore[arg-type]


def test_repeated_calls_are_identical() -> None:
    first = [hours_to_eligible(i, m, 0.5) for i in (5, 10, 15) for m in (0.0, 0.1, 0.3)]
    second = [hours_to_eligible(i, m, 0.5) for i in (5, 10, 15) for m in (0.0, 0.1, 0.3)]
    assert first == second


def test_module_imports_no_clock_or_network() -> None:
    tree = ast.parse(MODULE.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "math"}


@given(
    interval=st.integers(min_value=1, max_value=120),
    missed=st.floats(min_value=0, max_value=1),
    coverage=st.floats(min_value=0, max_value=1),
)
def test_hours_never_decrease_when_it_gets_harder(
    interval: int, missed: float, coverage: float
) -> None:
    base = hours_to_eligible(interval, missed, coverage)
    assert hours_to_eligible(interval, min(1.0, missed + 0.1), coverage) >= base - 1e-9
    assert hours_to_eligible(interval, missed, min(1.0, coverage + 0.1)) >= base - 1e-9
    if math.isfinite(base):
        assert 0.0 <= base <= WINDOW * (1 + 1e-12)


@given(
    interval=st.integers(min_value=1, max_value=120),
    other=st.integers(min_value=1, max_value=120),
    missed=st.floats(min_value=0, max_value=1),
    coverage=st.floats(min_value=0, max_value=1),
)
def test_faster_sampling_never_takes_longer(
    interval: int, other: int, missed: float, coverage: float
) -> None:
    faster, slower = sorted((interval, other))
    assert hours_to_eligible(faster, missed, coverage) <= (
        hours_to_eligible(slower, missed, coverage) + 1e-9
    )


def test_table_covers_intervals_and_miss_rates(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line.startswith("|")]
    assert rows[0] == "| sample interval | 0% missed | 10% missed | 30% missed |"
    assert len(rows) == 5  # header, separator, 5/10/15 min
    assert "| 5 min | 12.0 h | 13.3 h | 17.1 h |" in out
    assert "| 10 min | 24.0 h | never | never |" in out
    assert "| 15 min | never | never | never |" in out


def test_committed_report_matches_the_generated_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main() == 0
    table = capsys.readouterr().out.strip()
    report = (ROOT / "reports" / "index_coverage_table.md").read_text()
    assert table in report
