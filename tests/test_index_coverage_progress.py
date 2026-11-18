"""Tests for per-mint coverage progress and ETA tool (#231)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.market_data import Sample
from index.params import IndexParams
from tools.index_coverage_progress import compute_progress, load_seed_mints, main

ROOT = Path(__file__).resolve().parents[1]


def test_load_seed_mints(tmp_path: Path) -> None:
    seed_file = tmp_path / "seed_mints.txt"
    seed_file.write_text(
        "# Comment\n"
        "Mint11111111111111111111111111111111111111 \n\n"
        "Mint22222222222222222222222222222222222222 # comment"
    )
    mints = load_seed_mints(seed_file)
    assert mints == [
        "Mint11111111111111111111111111111111111111",
        "Mint22222222222222222222222222222222222222",
    ]
    assert load_seed_mints(tmp_path / "nonexistent.txt") == []


def test_compute_progress_synthetic() -> None:
    params = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
    now = 1731945600  # arbitrary unix timestamp

    mint_full = "Full111111111111111111111111111111111111"
    mint_partial = "Part222222222222222222222222222222222222"
    mint_empty = "Emp33333333333333333333333333333333333333"

    samples = []
    start = now - 24 * 3600
    for i in range(150):
        samples.append(Sample(mint=mint_full, t=start + i * 300))

    for i in range(72):
        samples.append(Sample(mint=mint_partial, t=start + i * 300))

    rows = compute_progress([mint_full, mint_partial, mint_empty], samples, now, params)
    assert len(rows) == 3

    row_dict = {r["mint"]: r for r in rows}

    assert row_dict[mint_full]["eta"] == "reached"
    assert row_dict[mint_full]["pct_threshold"] == 100.0

    assert row_dict[mint_partial]["pct_threshold"] == pytest.approx(50.0, abs=1.0)
    assert row_dict[mint_partial]["eta"] != "reached"
    assert row_dict[mint_partial]["eta"] != "never"

    assert row_dict[mint_empty]["samples"] == 0
    assert row_dict[mint_empty]["hours_covered"] == 0.0
    assert row_dict[mint_empty]["pct_threshold"] == 0.0
    assert row_dict[mint_empty]["eta"] == "never"


def test_format_table_and_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    samples_file = samples_dir / "2026-11-18.jsonl"
    now = 1731945600
    mint = "TestMint1111111111111111111111111111111"
    samples_file.write_text(json.dumps({"mint": mint, "t": now - 3600, "mc_usd": 1000.0}) + "\n")

    seed_file = tmp_path / "seed_mints.txt"
    seed_file.write_text(mint + "\n")

    params_file = tmp_path / "params.json"
    params_file.write_text((ROOT / "index" / "params.json").read_text())

    rc = main(
        [
            "--samples",
            str(samples_dir),
            "--params",
            str(params_file),
            "--seed-mints",
            str(seed_file),
            "--json",
        ],
        now=now,
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["mint"] == mint

    rc2 = main(
        [
            "--samples",
            str(samples_dir),
            "--params",
            str(params_file),
            "--seed-mints",
            str(seed_file),
        ],
        now=now,
    )
    assert rc2 == 0
    out = capsys.readouterr().out
    assert mint in out
