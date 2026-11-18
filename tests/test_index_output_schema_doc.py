"""docs/design/INDEX_OUTPUT_SCHEMA.md must match a fresh offline dry-run output (#224).

Every top-level key in the doc's table must be in the output (unless marked
optional or hourly-only), and the output must hold no top-level key the doc
does not list. Same for member rows and the metrics keys. No network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from test_index_e2e_offline import FAKE_KEY, _no_socket, _run  # noqa: F401

DOC = Path(__file__).resolve().parents[1] / "docs" / "design" / "INDEX_OUTPUT_SCHEMA.md"
ROW = re.compile(r"^\| `([a-z_0-9]+)` \|(.*)\|\s*$")


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = re.search(r"^#{2,3} ", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def _table_keys(section: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for line in section.splitlines() if (m := ROW.match(line))}


@pytest.fixture
def payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_KEY)
    assert _run(tmp_path, "out") == 0
    (path,) = (tmp_path / "out").iterdir()
    return json.loads(path.read_text())


def test_top_level_keys_match_doc(payload: dict) -> None:
    text = DOC.read_text()
    doc = _table_keys(_section(text, "## Top-level keys"))
    assert doc, "no top-level key table found in the doc"
    always = {k for k, rest in doc.items() if "| yes |" in f"|{rest}|"}
    assert always <= set(payload), f"documented but missing: {sorted(always - set(payload))}"
    assert set(payload) <= set(doc), f"undocumented keys: {sorted(set(payload) - set(doc))}"
    optional = set(doc) - always
    assert optional == {"exit_notice", "data_hold"}  # hourly-only / held-data keys


def test_member_and_metrics_keys_match_doc(payload: dict) -> None:
    text = DOC.read_text()
    row_doc = set(_table_keys(_section(text, "### `members[]`")))
    metrics_text = _section(text, "### `members[].metrics`")
    assert payload["members"], "offline dry run must produce at least one member"
    for member in payload["members"]:
        assert set(member) == row_doc
        for key in member["metrics"]:
            assert f"`{key}`" in metrics_text, f"metrics key {key} is not in the doc"


def test_doc_values_hold_on_output(payload: dict) -> None:
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", payload["as_of"])
    assert len(payload["params_hash"]) == len(payload["inputs_hash"]) == 64
    assert payload["dry_run"] is bool(payload["skipped_filters"])
    assert sum(m["weight_bps"] for m in payload["members"]) == 10_000
    assert set(payload["changes"]) == {"entered", "exited"}
    reasons = {e["reason"] for e in payload["excluded"]}
    allowed = {"insufficient_data", "weak_keyword", "denied"} | {f"F{i}" for i in range(1, 12)}
    assert reasons <= allowed


def test_doc_has_no_secret_shaped_text() -> None:
    text = DOC.read_text()
    assert FAKE_KEY not in text
    assert "api-key" not in text.lower()
    assert "HELIUS_API_KEY=" not in text
