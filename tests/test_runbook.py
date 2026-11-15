"""docs/RUNBOOK.md stays true to the current engine and test tree (issue #55)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sim.acceptance_v033 import all_rows
from sim.report_v033 import GAPS

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
# Nodeids tests/foo.py::test_bar; a [param] suffix is stripped before lookup. The
# check is an AST scan of top-level `def test_*`, so comments/nested defs do not count.
CITE = re.compile(r"tests/[A-Za-z0-9_./]+\.py::[A-Za-z0-9_]+")
# 32+ char base58: no wallet/key addresses in the runbook (public ids live in DECISIONS).
LONG_B58 = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,}\b")
REQUIRED = (
    "rewards.enabled",
    "needs kiwi APPROVED",
    "conservation",
    "price feed",
    "missing events",
    "go / no-go",
    "draws.enabled",
    "harmonic",
    "pending",
    "merkle",
)


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _top_level_tests(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }


def _table_rows(section: str) -> list[list[str]]:
    """Data rows of the markdown tables inside one `## ...` section."""
    text = _text()
    body = text[text.index(section) :]
    end = body.find("\n## ", 1)
    rows: list[list[str]] = []
    for line in (body if end == -1 else body[:end]).splitlines():
        line = line.strip()
        if not line.startswith("| ") or line.startswith("| # |"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not all(set(cell) <= set("-: ") for cell in cells):
            rows.append(cells)
    return rows


def test_runbook_exists_and_covers_required_topics() -> None:
    text = _text()
    assert [topic for topic in REQUIRED if topic not in text] == []
    assert "38 PASS" in text and "9 GAP" in text


def test_runbook_has_no_wallet_addresses() -> None:
    found = set(LONG_B58.findall(_text()))
    assert found == set(), f"address-like strings in RUNBOOK.md: {sorted(found)}"


def test_cited_tests_exist() -> None:
    cites = sorted({c.split("[", 1)[0] for c in CITE.findall(_text())})
    assert cites, "runbook should cite tests by nodeid"
    cache: dict[str, set[str]] = {}
    missing: list[str] = []
    for cite in cites:
        path, name = cite.split("::", 1)
        src = ROOT / path
        if path not in cache:
            cache[path] = _top_level_tests(src) if src.is_file() else set()
        if name not in cache[path]:
            missing.append(cite)
    assert missing == [], missing


def test_checklists_and_failure_modes_map_to_a_test_or_gap() -> None:
    checklist = [r for r in _table_rows("## 5. Offline go / no-go checklist") if r[0].isdigit()]
    failures = [r for r in _table_rows("## 4. Failure modes") if r[0] != "Failure"]
    assert len(checklist) >= 20 and len(failures) >= 10
    for row in [*checklist, *failures]:
        line = " | ".join(row).lower()
        assert "tests/" in line or "gap" in line or "needs kiwi" in line, row


def test_every_section_14_row_is_listed() -> None:
    text = _text()
    missing = [name for name, _cond, _fn in all_rows() if name not in text]
    missing += [name for name, _kind, _why in GAPS if name not in text]
    assert missing == [], missing
