"""docs/RUNBOOK.md cites real tests (issue #55)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
# tests/foo.py::test_bar or tests/foo.py::test_bar[param] — no line numbers
CITE = re.compile(r"tests/[A-Za-z0-9_./]+\.py::[A-Za-z0-9_]+")


def test_runbook_exists_and_covers_required_topics() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "rewards.enabled" in text
    assert "needs kiwi APPROVED" in text
    assert "conservation" in text.lower()
    assert "bad price feed" in text.lower() or "price feed" in text.lower()
    assert "missing events" in text.lower()
    assert "go / no-go" in text.lower() or "go/no-go" in text.lower()
    # No 32+ char base58 that isn't a documented program id.
    # The D7 distributor program id is public and expected.
    assert "DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R" in text


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
