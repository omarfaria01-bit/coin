"""Contract test for docs/design/INDEX_OUTPUT_SCHEMA.md (issue #224).

Generates fresh offline dry runs from the tests/test_index_e2e_offline.py
fixtures; fails on undocumented or missing keys and triggers conditional ones.
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
import test_index_e2e_offline as e2e

from adapters.helius_client import HeliusClient
from index.emergency import apply_emergency
from index.filters import Metrics
from index.params import IndexParams

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "design" / "INDEX_OUTPUT_SCHEMA.md"

_KEYS = re.compile(
    r"<!-- index-output-schema-keys:start -->\s*```json\s*(\{.*?\})\s*```\s*"
    r"<!-- index-output-schema-keys:end -->",
    re.DOTALL,
)
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


@pytest.fixture(autouse=True)
def _no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if anything opens a socket: every run here is offline."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is not allowed in tests/test_index_output_schema_doc.py")

    monkeypatch.setattr(socket, "socket", refuse)


def _doc_keys() -> dict[str, list[str]]:
    match = _KEYS.search(DOC.read_text())
    assert match is not None, "the machine-readable key block is missing from the doc"
    keys: dict[str, list[str]] = json.loads(match.group(1))
    for name, values in keys.items():
        assert values, f"{name} is empty in the doc"
        assert len(values) == len(set(values)), f"{name} repeats a key in the doc"
    return keys


def _documented(keys: dict[str, list[str]]) -> set[str]:
    return set(keys["top_level_required"]) | set(keys["top_level_conditional"])


def _params(tmp_path: Path, name: str, *, hourly: bool = False) -> Path:
    """Fixture params in dry-run mode, optionally hourly with size 1."""
    params = json.loads(e2e.PARAMS.read_text())
    params["dry_run"]["skip_filters"] = ["F3"]
    if hourly:
        params["rebalance_hours"] = 1
        params["membership"] = {"size": 1, "enter_rank": 1, "exit_rank": 1}
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(params))
    return path


def _fixed(*rows: Metrics) -> Callable[..., list[Metrics]]:
    """A measure() that returns exactly `rows`, for the mints the run asks about."""
    by_mint = {row.mint: row for row in rows}

    def measure(_client: object, mints: list[str], **_kwargs: object) -> list[Metrics]:
        return [by_mint[mint] for mint in mints if mint in by_mint]

    return measure


def _run(tmp_path: Path, run: str, *, params: Path, measure: Callable[..., list[Metrics]]) -> None:
    argv = [
        "--as-of",
        e2e.AS_OF,
        "--out",
        str(tmp_path / run),
        "--params",
        str(params),
        "--overrides",
        str(e2e.OVERRIDES),
        "--samples",
        str(e2e._samples_dir(tmp_path)),
    ]
    client = HeliusClient(
        e2e.FAKE_KEY,
        e2e._refuse_transport,
        sleep=lambda _seconds: None,
        rpc_interval=0,
        das_interval=0,
        dex_interval=0,
    )
    rc = e2e.main(
        argv,
        client=client,
        measure=measure,
        discover=lambda *_args, **_kwargs: e2e._fixture_discovery(),
    )
    assert rc == 0


def _payload(directory: Path) -> dict:
    files = sorted(path for path in directory.glob("*.json") if path.name != "emergency.json")
    assert len(files) == 1, files
    return json.loads(files[0].read_text())


def _base() -> Metrics:
    return e2e._fixture_candidates()[0]


def _rival() -> Metrics:
    """A second passing candidate borrowed from the fixture mints, ranked above the base."""
    other = e2e._fixture_candidates()[1]
    return replace(_base(), mint=other.mint, ticker="GTAVI", mc_usd=3_000_000.0)


def test_fresh_dry_run_has_exactly_the_documented_top_level_keys(tmp_path: Path) -> None:
    keys = _doc_keys()
    _run(tmp_path, "run", params=_params(tmp_path, "daily"), measure=e2e._measure)
    payload = _payload(tmp_path / "run")

    # No undocumented top-level key, and every documented unconditional key exists.
    assert sorted(payload) == sorted(keys["top_level_required"])
    assert set(payload) <= _documented(keys)

    assert len(payload["members"]) > 0
    for member in payload["members"]:
        assert sorted(member) == sorted(keys["member"])
        assert sorted(member["metrics"]) == sorted(keys["member_metrics"])
    assert payload["excluded"]
    for row in payload["excluded"]:
        assert (
            set(keys["excluded"])
            <= set(row)
            <= set(keys["excluded"]) | set(keys.get("excluded_conditional", []))
        )
    assert sorted(payload["changes"]) == sorted(keys["changes"])
    assert payload["emergency"] == []

    blocks = [json.loads(match.group(1)) for match in _JSON_BLOCK.finditer(DOC.read_text())]
    assert len(blocks) == 3  # key block + the two real examples
    top = next(block for block in blocks if "as_of" in block)
    member = next(block for block in blocks if "weight_bps" in block)
    assert set(top) <= _documented(keys)
    assert sorted(member) == sorted(keys["member"])
    assert sorted(member["metrics"]) == sorted(keys["member_metrics"])


def test_conditional_keys_are_produced_and_documented(tmp_path: Path) -> None:
    keys = _doc_keys()
    documented = _documented(keys)
    base, rival = _base(), _rival()

    # data_hold: the member's new hour is insufficient_data, so last metrics are carried.
    daily = _params(tmp_path, "daily")
    _run(tmp_path, "hold", params=daily, measure=_fixed(base))
    _run(tmp_path, "hold", params=daily, measure=_fixed(replace(base, coverage=None)))
    held = _payload(tmp_path / "hold")
    assert held["data_hold"] == [base.mint]
    assert base.mint in {member["mint"] for member in held["members"]}
    assert set(held) <= documented
    assert "data_hold" in keys["top_level_conditional"]

    # exit_notice: hourly mode defers a rank exit by one hour.
    hourly = _params(tmp_path, "hourly", hourly=True)
    _run(tmp_path, "hourly", params=hourly, measure=_fixed(base))
    _run(tmp_path, "hourly", params=hourly, measure=_fixed(base, rival))
    deferred = _payload(tmp_path / "hourly")
    assert deferred["exit_notice"] == [base.mint]
    assert [member["mint"] for member in deferred["members"]] == [rival.mint, base.mint]
    assert set(deferred) <= documented
    assert "exit_notice" in keys["top_level_conditional"]

    # A filter failure exits at once, and the exited entry keeps its documented shape.
    failed = replace(base, liquidity_usd=1_000.0)
    _run(tmp_path, "hourly", params=hourly, measure=_fixed(rival, failed))
    exited = _payload(tmp_path / "hourly")
    assert exited["exit_notice"] == []
    assert exited["changes"]["exited"]
    for row in exited["changes"]["exited"]:
        assert sorted(row) == sorted(keys["change_exited"])
    assert base.mint not in {member["mint"] for member in exited["members"]}


def test_emergency_entries_use_the_documented_shape(tmp_path: Path) -> None:
    keys = _doc_keys()
    params_path = _params(tmp_path, "daily")
    _run(tmp_path, "run", params=params_path, measure=e2e._measure)
    params = IndexParams.model_validate(json.loads(params_path.read_text()))

    payload = _payload(tmp_path / "run")
    gone = payload["members"][0]["mint"]
    removed = apply_emergency(payload, gone, "rug_flag", "2026-11-18T18:00:00Z", params)
    assert gone not in {m["mint"] for m in removed["members"]}  # D35: other coins may remain
    assert sorted(removed["emergency"][0]) == sorted(keys["emergency"])
