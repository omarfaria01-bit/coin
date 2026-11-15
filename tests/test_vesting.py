"""Soft-mode vesting breach check (§11)."""

from __future__ import annotations

from engine.vesting import breaches_soft_lock


def test_breaches_soft_lock() -> None:
    assert breaches_soft_lock(9, 10) is True
    assert breaches_soft_lock(10, 10) is False
    assert breaches_soft_lock(11, 10) is False
