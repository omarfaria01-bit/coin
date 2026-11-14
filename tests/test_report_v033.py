"""#84 step 3b: reports/sim_<date>.md lists every §14 row as PASS, FAIL or GAP."""

from __future__ import annotations

from pathlib import Path

import pytest

import sim.report_v033 as rep
from sim.acceptance_v033 import all_rows
from sim.run import main


@pytest.fixture(scope="module")
def short_report() -> tuple[str, list]:
    return rep.build(seeds=1, days=12)


def test_every_row_and_gap_is_listed(short_report) -> None:
    text, rows = short_report
    for name, _, _ in all_rows():
        assert f"| {name} |" in text
    for name, why in rep.GAPS:
        assert f"| {name} | GAP | {why} |" in text
    names = {r.name for r in rows}
    assert {"Trader in 4h cycles vs a 7-day holder", "Volume −90% overnight"} <= names
    assert "| rewards gini_rewards" in text and "€100 holder: days_to_first_payout" in text


def test_failures_are_reported_and_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = rep.RowResult("Broken", "never", 0, 1, "seed 0: boom")
    monkeypatch.setattr(rep, "build", lambda seeds: ("| Broken | never | FAIL |\n", [bad]))
    out = tmp_path / "r.md"
    assert main(["--report", "--seeds", "1", "--out", str(out)]) == 1
    assert "FAIL" in out.read_text(encoding="utf-8")


def test_strict_fails_while_gaps_are_left(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = rep.RowResult("Fine", "always", 1, 1, "seed 0: ok")
    monkeypatch.setattr(rep, "build", lambda seeds: ("ok\n", [ok]))
    assert main(["--report", "--seeds", "1", "--out", str(tmp_path / "a.md")]) == 0
    assert main(["--report", "--seeds", "1", "--strict", "--out", str(tmp_path / "b.md")]) == 1
    monkeypatch.setattr(rep, "GAPS", ())
    assert main(["--report", "--seeds", "1", "--strict", "--out", str(tmp_path / "c.md")]) == 0
