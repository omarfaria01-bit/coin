"""#84 step 2: the v0.3.3 §14 attack rows run on the real engine and reach the runner."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import sim.acceptance_attacks_v033 as att
from sim.run import main


@pytest.mark.parametrize(("name", "fn"), [(n, f) for n, _, f in att.ROWS])
def test_every_attack_row_passes_on_three_seeds(name: str, fn) -> None:
    for seed in range(3):
        out = fn(random.Random(f"{name}:{seed}"))
        assert out.passed, f"{name} seed {seed}: {out.evidence}"


def test_attack_rows_are_in_the_report(tmp_path: Path) -> None:
    report = tmp_path / "acc.md"
    assert main(["--acceptance", "--seeds", "1", "--out", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    for name, cond, _ in att.ROWS:
        assert f"| {name} | {cond} | PASS |" in text


def test_failing_attack_row_fails_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = ("Broken attack", "never", lambda rng: att.Outcome(False, "boom"))
    monkeypatch.setattr(att, "ROWS", (bad,))
    report = tmp_path / "bad.md"
    assert main(["--acceptance", "--seeds", "1", "--out", str(report)]) == 1
    assert "| Broken attack | never | FAIL (1/1 seeds) | seed 0: boom |" in report.read_text(
        "utf-8"
    )
