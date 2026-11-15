"""#133: the offline rows that close the non-flag §14 GAPs run on the real engine."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import sim.gap_rows_v033 as gap
from sim.run import main


@pytest.mark.parametrize(("name", "fn"), [(n, f) for n, _, f in gap.ROWS])
def test_every_gap_row_passes_on_three_seeds(name: str, fn) -> None:
    for seed in range(3):
        out = fn(random.Random(f"{name}:{seed}"))
        assert out.passed, f"{name} seed {seed}: {out.evidence}"


def test_gap_rows_are_in_the_acceptance_report(tmp_path: Path) -> None:
    report = tmp_path / "acc.md"
    assert main(["--acceptance", "--seeds", "1", "--out", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    for name, cond, _ in gap.ROWS:
        assert f"| {name} | {cond} | PASS |" in text
