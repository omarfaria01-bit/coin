"""COIN_MATH §14 acceptance scenarios (harness on main; not stacked on #33)."""

from __future__ import annotations

from sim.acceptance import run_all


def test_section_14_remaining_rows_pass() -> None:
    rows = run_all()
    names = [r.name for r in rows]
    assert names == [
        "whale_cap",
        "underwater_farmer",
        "sybil_split",
        "zero_inflow_pot_decay",
        "draws_fairness",
    ]
    failed = [r for r in rows if not r.passed]
    assert not failed, "; ".join(f"{r.name}: {r.evidence}" for r in failed)
