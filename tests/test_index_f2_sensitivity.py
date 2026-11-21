"""#251: saved inputs replay to the published output; F2 sensitivity on a small fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from index.select import canonical_json, inputs_doc, run_index
from tests.test_run_index import AS_OF, P, _run, good, mint
from tools.index_f2_sensitivity import load_inputs, main, render, sensitivity

LIQ = [8_000, 12_000, 20_000, 30_000, 45_000, 60_000, 80_000, 120_000]


def _doc(tmp: Path) -> Path:
    cands = [
        good(i + 1, liquidity_usd=float(liq), ticker=f"T{liq // 1000}") for i, liq in enumerate(LIQ)
    ]
    out = run_index(cands, [], P, _overrides(), AS_OF, "test")
    doc = inputs_doc(cands, [], _overrides())
    doc.update(as_of=out["as_of"], inputs_hash=out["inputs_hash"])
    path = tmp / "2026-11-18T19.json"
    path.write_bytes(canonical_json(doc))
    return path


def _overrides():
    from index.params import Overrides

    return Overrides()


def test_run_index_saves_inputs_that_hash_to_the_output(tmp_path: Path) -> None:
    assert _run(tmp_path, lambda *_a, **_k: [good(1), good(2)], mints=mint(1)) == 0
    published = json.loads((tmp_path / "out" / "2026-11-18T19.json").read_text())
    saved = tmp_path / "inputs" / "2026-11-18T19.json"  # next to --samples, never in out/
    assert load_inputs(saved)["inputs_hash"] == published["inputs_hash"]
    assert not list((tmp_path / "out").glob("*inputs*"))


def test_f2_sensitivity_counts_and_weights(tmp_path: Path) -> None:
    doc = load_inputs(_doc(tmp_path))
    rows = sensitivity(doc, P, [5_000, 10_000, 25_000, 50_000])
    by = {r["threshold"]: r for r in rows}
    # $5k: T8 still fails another filter (F11, mc/liquidity 125 > 100): only F2 moves
    assert [by[t]["members"] for t in (5_000, 10_000, 25_000, 50_000)] == [7, 7, 5, 3]
    assert [by[t]["eligible"] for t in (5_000, 10_000, 25_000, 50_000)] == [7, 7, 5, 3]
    assert [by[t]["f2_excluded"] for t in (5_000, 10_000, 25_000, 50_000)] == [0, 1, 3, 5]
    for r in rows:
        assert r["bps_sum"] == 10_000
    assert by[5_000]["below_prescreen"] and not by[50_000]["below_prescreen"]
    text = render(doc, rows)
    assert "| 50,000 | 3 | 3 |" in text and "lower bound" in text


def test_eligible_counts_passers_beyond_the_top_ten(tmp_path: Path) -> None:
    """12 coins pass every filter: 12 eligible, only 10 become members (weights still 10,000)."""
    cands = [good(i, liquidity_usd=120_000.0, ticker=f"T{i}") for i in range(1, 13)]
    out = run_index(cands, [], P, _overrides(), AS_OF, "test")
    doc = inputs_doc(cands, [], _overrides())
    doc.update(as_of=out["as_of"], inputs_hash=out["inputs_hash"])
    path = tmp_path / "2026-11-18T20.json"
    path.write_bytes(canonical_json(doc))

    rows = sensitivity(load_inputs(path), P, [50_000])
    assert rows[0]["eligible"] == 12 and rows[0]["members"] == 10
    assert rows[0]["bps_sum"] == 10_000 and len(rows[0]["top"]) == 10
    assert "| 50,000 | 12 | 10 |" in render(doc, rows)


def test_tampered_inputs_are_refused(tmp_path: Path) -> None:
    path = _doc(tmp_path)
    doc = json.loads(path.read_text())
    doc["candidates"][0]["liquidity_usd"] = 999_999.0
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="inputs_hash mismatch"):
        load_inputs(path)


def test_cli_on_a_directory(tmp_path: Path, capsys) -> None:
    _doc(tmp_path)
    assert main([str(tmp_path), "--thresholds", "50000"]) == 0
    assert "| 50,000 | 3 | 3 |" in capsys.readouterr().out
    assert main([str(tmp_path / "empty_dir_missing")]) == 2
