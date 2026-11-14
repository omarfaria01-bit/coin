"""docs/RUNBOOK.md cites real tests (issue #55)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
# Nodeids of the form tests/foo.py::test_bar. Parametrized suffixes ([param])
# are not parsed; a commented-out or nested `def test_bar(` would also match.
# Good enough as a docs guard, not a collection-accurate inventory.
CITE = re.compile(r"tests/[A-Za-z0-9_./]+\.py::[A-Za-z0-9_]+")
ALLOWED_LONG_BASE58 = frozenset(
    {
        "DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R",  # D7 jup-ag/distributor
    }
)
# Base58 pubkey-shaped tokens (32+ chars, no lowercase L / 0 / I / O ambiguity set
# is not enforced; this is a length+alphabet scan only).
LONG_B58 = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,}\b")


def test_runbook_exists_and_covers_required_topics() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "rewards.enabled" in text
    assert "needs kiwi APPROVED" in text
    assert "conservation" in text.lower()
    assert "bad price feed" in text.lower() or "price feed" in text.lower()
    assert "missing events" in text.lower()
    assert "go / no-go" in text.lower() or "go/no-go" in text.lower()
    found = set(LONG_B58.findall(text))
    unexpected = found - ALLOWED_LONG_BASE58
    assert "DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R" in found
    assert unexpected == set(), unexpected


def test_cited_tests_exist() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    cites = sorted(set(CITE.findall(text)))
    assert cites, "runbook should cite tests by nodeid"
    missing: list[str] = []
    for cite in cites:
        path, name = cite.split("::", 1)
        src = ROOT / path
        if not src.is_file() or f"def {name}(" not in src.read_text(encoding="utf-8"):
            missing.append(cite)
    assert missing == [], missing
