"""sim.run exit codes (--strict)."""

from __future__ import annotations

from pathlib import Path

from sim.run import exit_code, main


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
