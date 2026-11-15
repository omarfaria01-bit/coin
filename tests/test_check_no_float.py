"""The payout path stays float-free (COIN_MATH v0.3.3 §0); ratchet in tools/check_no_float.py."""

from __future__ import annotations

from pathlib import Path

from tools.check_no_float import BASELINE, check, violations


def test_repo_passes_the_ratchet() -> None:
    assert not BASELINE
    assert check() == []


def test_detects_math_float_literal_and_float_name() -> None:
    src = "import math\n\ndef f(x):\n    return float(x) * 0.5\n\nclass C:\n    y: float\n"
    found = violations(src)
    assert found["<module>"] == ["line 1: import math"]
    assert found["f"] == ["line 4: float", "line 4: float literal 0.5"]
    assert found["C"] == ["line 7: float"]
    assert violations("from fractions import Fraction\nX = Fraction(1, 2) + 3\n") == {}


def test_new_violation_and_stale_baseline_both_fail(tmp_path: Path) -> None:
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "rewards.py").write_text("def new_payout(x):\n    return x * 1.5\n")
    errs = check(tmp_path, frozenset({("rewards", "old_gone")}))
    assert any("new_payout" in e and "1.5" in e for e in errs)
    assert any("stale BASELINE entry ('rewards', 'old_gone')" in e for e in errs)
    assert check(tmp_path, frozenset({("rewards", "new_payout")})) == []
