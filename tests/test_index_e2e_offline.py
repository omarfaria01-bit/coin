"""run_index dry-run end to end on fixture data: deterministic, no secrets, no network."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import base58
import pytest

from index.filters import Metrics
from index.params import FILTER_CODES, IndexParams
from tools.run_index import main

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-11-18T19:00:00+00:00"
FAKE_KEY = "fake-key-123"
N_CANDIDATES = 12


class FakeClient:
    requests = {"rpc": 0, "das": 0, "parsed": 0, "dex": 0}


def _mint(i: int) -> str:
    return base58.b58encode(bytes([i]) * 32).decode()


def _row(i: int) -> Metrics:
    return Metrics(
        mint=_mint(i),
        ticker="GTA6",
        name="Vice City",
        coverage=1.0,
        age_hours=30.0,
        liquidity_usd=120_000.0 + i * 1_000,
        mc_usd=1_000_000.0 + i * 50_000,
        top10_pct=20.0,
        total_fees_sol=40.0,
        window_fees_sol=12.0,
        bundle_pct=2.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        unique_traders=500,
        volume_usd=100_000.0 + i * 1_000,
    )


def _discover(*_a: object, **_k: object) -> list[dict]:
    return [{"mint": _mint(i), "name": "Vice City", "symbol": "GTA6"} for i in range(1, 13)]


def _measure(_client: object, mints: list[str], **_kw: object) -> list[Metrics]:
    return [_row(i) for i in range(1, N_CANDIDATES + 1) if _mint(i) in set(mints)]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("network socket opened")

    monkeypatch.setattr(socket, "socket", boom)


def _params(tmp: Path) -> Path:
    base = json.loads((ROOT / "index" / "params.json").read_text())
    params = IndexParams.model_validate(base).model_copy(
        update={"rebalance_hours": 1, "self_mint": None}
    )
    raw = params.model_dump(mode="json")
    raw["dry_run"] = {"skip_filters": [sorted(FILTER_CODES, key=lambda c: int(c[1:]))[0]]}
    path = tmp / "params.json"
    path.write_text(json.dumps(raw))
    return path


def _argv(tmp: Path, out: Path) -> list[str]:
    return [
        "--as-of",
        AS_OF,
        "--out",
        str(out),
        "--params",
        str(_params(tmp)),
        "--overrides",
        str(ROOT / "index" / "overrides.json"),
        "--samples",
        str(tmp / "no_samples"),
    ]


def _run(tmp: Path, out: Path) -> int:
    return main(_argv(tmp, out), client=FakeClient(), measure=_measure, discover=_discover)


def test_dry_run_twice_is_byte_identical_and_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_KEY)
    first, second = tmp_path / "a", tmp_path / "b"
    assert _run(tmp_path, first) == 0
    assert _run(tmp_path, second) == 0
    files_a, files_b = sorted(first.glob("*.json")), sorted(second.glob("*.json"))
    assert [f.name for f in files_a] == [f.name for f in files_b] == ["2026-11-18T19.dryrun.json"]
    raw = files_a[0].read_bytes()
    assert raw == files_b[0].read_bytes()

    payload = json.loads(raw)
    assert payload["dry_run"] is True
    members = payload["members"]
    assert 0 < len(members) <= 10
    assert sum(m["weight_bps"] for m in members) == 10_000

    seen = capsys.readouterr()
    assert FAKE_KEY not in raw.decode()
    assert FAKE_KEY not in seen.out
    assert FAKE_KEY not in seen.err


def test_live_mode_without_key_exits_2_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    out = tmp_path / "out"
    assert main(_argv(tmp_path, out), measure=_measure, discover=_discover) == 2
    assert not out.exists()
    assert "HELIUS_API_KEY is not set" in capsys.readouterr().err
