"""Offline end-to-end dry run of tools/run_index.py on the recorded fixtures (#194).

Two runs with the same fixture candidates and the same fixed as-of must write
byte-identical files. No socket may be opened and the fake API key must never
appear in the output file, on stdout or on stderr.
"""

from __future__ import annotations

import json
import socket
from collections import defaultdict
from pathlib import Path

import pytest

from adapters.helius_client import HeliusClient
from adapters.market_data import coverage, mean
from index.filters import Metrics
from tools.run_index import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "index"
SAMPLES = FIXTURES / "samples.jsonl"
PARAMS = FIXTURES / "params_small.json"
OVERRIDES = FIXTURES / "overrides_empty.json"

AS_OF = "2026-11-18T18:00:00+00:00"
UNIX = 1795024800  # 2026-11-18T18:00:00Z
WINDOW_START = UNIX - 3600  # params_small: window_hours=1
SAMPLE_SECONDS = 300  # params_small: sample_minutes=5

# The fixtures record market samples but no on-chain facts. These fixed values
# stand in for the Helius RPC/parsed-events readings; no network is used.
CHAIN_FACTS = {
    "total_fees_sol": 150.0,
    "window_fees_sol": 40.0,
    "bundle_pct": 2.0,
    "dev_pct": 1.0,
    "creator_launches_7d": 1,
    "mint_authority_revoked": True,
    "freeze_authority_revoked": True,
    "unique_traders": 500,
    "independent_traders": 500,
    "roundtrip_share": 0.0,
    "volume_wallets": 100,
    "median_trade_sol": 0.1,
}

FAKE_KEY = "fake-key-123"  # never a real key


@pytest.fixture(autouse=True)
def _no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if anything opens a socket (no network in an offline test)."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is not allowed in tests/test_index_e2e_offline.py")

    monkeypatch.setattr(socket, "socket", refuse)


def _fixture_rows() -> list[dict]:
    return [json.loads(line) for line in SAMPLES.read_text().splitlines() if line.strip()]


def _latest_volume(rows: list[dict]) -> float | None:
    points = [row for row in rows if row.get("volume_h24_usd") is not None]
    if not points:
        return None
    return float(max(points, key=lambda row: row["ts"])["volume_h24_usd"])


def _fixture_candidates() -> list[Metrics]:
    """One deterministic candidate per mint recorded in tests/fixtures/index/samples.jsonl."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in _fixture_rows():
        grouped[row["mint"]].append(row)

    out: list[Metrics] = []
    for mint, rows in grouped.items():
        inside = [row for row in rows if WINDOW_START <= row["ts"] < UNIX]
        named = next(row for row in rows if row.get("name") and row.get("ticker"))
        created_ms = named.get("pair_created_at")
        out.append(
            Metrics(
                mint=mint,
                ticker=str(named["ticker"]),
                name=str(named["name"]),
                coverage=coverage(
                    (row["ts"] for row in inside), WINDOW_START, UNIX, SAMPLE_SECONDS
                ),
                age_hours=None if created_ms is None else (UNIX - created_ms / 1000) / 3600,
                liquidity_usd=mean(
                    row["liquidity_usd"] for row in inside if row.get("liquidity_usd") is not None
                ),
                mc_usd=mean(
                    row["market_cap_usd"] for row in inside if row.get("market_cap_usd") is not None
                ),
                volume_usd=_latest_volume(inside),
                **CHAIN_FACTS,
            )
        )
    return out


def _fixture_discovery() -> list[dict]:
    seen: dict[str, dict] = {}
    for row in _fixture_rows():
        name = row.get("name")
        ticker = row.get("ticker")
        if not name or not ticker:
            continue
        seen.setdefault(row["mint"], {"mint": row["mint"], "name": name, "symbol": ticker})
    return list(seen.values())


def _measure(_client: object, mints: list[str], **_kwargs: object) -> list[Metrics]:
    by_mint = {row.mint: row for row in _fixture_candidates()}
    return [by_mint[mint] for mint in mints]


def _params(tmp_path: Path) -> Path:
    """params_small in dry-run mode: F3 (top-10 holders) is skipped, so top10 stays unmeasured."""
    params = json.loads(PARAMS.read_text())
    params["dry_run"]["skip_filters"] = ["F3"]
    path = tmp_path / "params.json"
    path.write_text(json.dumps(params))
    return path


def _samples_dir(tmp_path: Path) -> Path:
    """The fixture samples in the CLI's `--samples` schema ({mint,t,mc_usd,...}, not {ts,...})."""
    directory = tmp_path / "samples"
    directory.mkdir(exist_ok=True)
    lines = [
        json.dumps(
            {
                "mint": row["mint"],
                "t": int(row["ts"]),
                "mc_usd": row.get("market_cap_usd"),
                "liquidity_usd": row.get("liquidity_usd"),
                "volume_usd": row.get("volume_h24_usd"),
            }
        )
        for row in _fixture_rows()
    ]
    (directory / "2026-11-18.jsonl").write_text("\n".join(lines) + "\n")
    return directory


def _run(tmp_path: Path, run: str) -> int:
    argv = [
        "--as-of",
        AS_OF,
        "--out",
        str(tmp_path / run),
        "--params",
        str(_params(tmp_path)),
        "--overrides",
        str(OVERRIDES),
        "--samples",
        str(_samples_dir(tmp_path)),
    ]
    client = HeliusClient(
        FAKE_KEY,
        _refuse_transport,
        sleep=lambda _seconds: None,
        rpc_interval=0,
        das_interval=0,
        dex_interval=0,
    )
    return main(
        argv,
        client=client,
        measure=_measure,
        discover=lambda *_args, **_kwargs: _fixture_discovery(),
    )


def _refuse_transport(_method: str, _url: str, _body: dict | None) -> tuple[int, object]:
    raise AssertionError("network is not allowed in tests/test_index_e2e_offline.py")


def test_two_runs_are_byte_identical_and_never_leak_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_KEY)

    assert _run(tmp_path, "run_a") == 0
    first = capsys.readouterr()
    assert _run(tmp_path, "run_b") == 0
    second = capsys.readouterr()

    names_a = sorted(path.name for path in (tmp_path / "run_a").iterdir())
    names_b = sorted(path.name for path in (tmp_path / "run_b").iterdir())
    assert names_a == names_b == ["2026-11-18.dryrun.json"]

    blob_a = (tmp_path / "run_a" / names_a[0]).read_bytes()
    blob_b = (tmp_path / "run_b" / names_b[0]).read_bytes()
    assert blob_a == blob_b

    payload = json.loads(blob_a)
    assert payload["dry_run"] is True
    assert payload["skipped_filters"] == ["F3"]
    assert payload["as_of"] == "2026-11-18T18:00:00Z"
    members = payload["members"]
    assert 0 < len(members) <= 10
    assert [member["rank"] for member in members] == list(range(1, len(members) + 1))
    assert {member["mint"] for member in members} <= {row.mint for row in _fixture_candidates()}
    assert sum(member["weight_bps"] for member in members) == 10_000
    assert all(member["weight_bps"] >= 0 for member in members)

    for blob in (blob_a, blob_b):
        assert FAKE_KEY.encode() not in blob
    for captured in (first, second):
        assert FAKE_KEY not in captured.out
        assert FAKE_KEY not in captured.err


def test_missing_key_live_mode_exits_two_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    out = tmp_path / "out"
    argv = [
        "--as-of",
        AS_OF,
        "--out",
        str(out),
        "--params",
        str(_params(tmp_path)),
        "--overrides",
        str(OVERRIDES),
        "--samples",
        str(_samples_dir(tmp_path)),
    ]
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert "HELIUS_API_KEY is not set" in captured.err
    assert not out.exists()
    assert FAKE_KEY not in captured.out + captured.err
