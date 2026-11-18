"""#84 step 1: the v0.3.3 §14 rows run on the real engine and the runner fails loudly."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import sim.acceptance_v033 as acc
from sim.run import main


@pytest.mark.parametrize(("name", "fn"), [(n, f) for n, _, f in acc.ROWS])
def test_every_row_passes_on_three_seeds(name: str, fn) -> None:
    for seed in range(3):
        out = fn(random.Random(f"{name}:{seed}"))
        assert out.passed, f"{name} seed {seed}: {out.evidence}"


def test_failing_row_is_reported_with_worst_seed_and_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = ("Broken row", "never", lambda rng: acc.Outcome(rng.random() < 0, "boom"))
    monkeypatch.setattr(acc, "ROWS", (*acc.ROWS[:1], bad))
    report = tmp_path / "acc.md"
    assert main(["--acceptance", "--seeds", "2", "--out", str(report)]) == 1
    text = report.read_text(encoding="utf-8")
    assert "| Broken row | never | FAIL (2/2 seeds) | seed 0: boom |" in text
    assert "| Holding time 0h–4h then flat |" in text and "| PASS |" in text


def test_all_rows_pass_exit_0(tmp_path: Path) -> None:
    assert main(["--acceptance", "--seeds", "2", "--out", str(tmp_path / "ok.md")]) == 0
