"""Hourly exit grace, and emergency removal only when the check has data."""

from __future__ import annotations

import json
from pathlib import Path

import base58

from index.params import IndexParams
from tools.index_watch import defer_exit
from tools.run_index import main

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))


def mint(i: int) -> str:
    return base58.b58encode(bytes([i]) * 32).decode()


def _payload(members, exited):
    return {"members": members, "changes": {"exited": exited}}


def test_rank_exit_waits_one_hour_and_a_filter_failure_does_not() -> None:
    weak = {"mint": "A", "log_s": 1.0, "rank": 1, "weight_bps": 10000}
    strong = {"mint": "B", "log_s": 2.0, "rank": 1, "weight_bps": 10000}
    exited = [{"mint": "A", "reason": "rank_2"}]
    first = defer_exit(_payload([strong], exited), {"members": [weak]}, P)
    assert {m["mint"] for m in first["members"]} == {"A", "B"}
    assert first["exit_notice"] == ["A"]
    second = defer_exit(_payload([dict(strong)], [{"mint": "A", "reason": "rank_2"}]), first, P)
    assert [m["mint"] for m in second["members"]] == ["B"]
    kept = defer_exit(_payload([strong], [{"mint": "A", "reason": "F6"}]), {"members": [weak]}, P)
    assert [m["mint"] for m in kept["members"]] == ["B"]
    assert kept["exit_notice"] == []


class Fake:
    requests = {"rpc": 0, "das": 0, "parsed": 0, "dex": 0}

    def __init__(self, authority: str | None):
        self.authority = authority

    def pairs(self, _mints):
        return []

    def rpc(self, method, _params):
        if method == "getAccountInfo" and self.authority is not None:
            info = {
                "supply": "1000",
                "decimals": 0,
                "mintAuthority": self.authority,
                "freezeAuthority": None,
            }
            return {"value": {"data": {"parsed": {"info": info}}}}
        return {}


def test_missing_authority_does_not_remove_and_a_live_authority_does(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    member = {"mint": mint(1), "log_s": 1.0, "rank": 1, "weight_bps": 10000}
    (out / "2026-11-18T18.json").write_text(json.dumps({"members": [member], "emergency": []}))
    argv = [
        "--as-of",
        "2026-11-18T19:00:00+00:00",
        "--out",
        str(out),
        "--mode",
        "emergency",
        "--params",
        str(ROOT / "index" / "params.json"),
        "--overrides",
        str(ROOT / "index" / "overrides.json"),
    ]
    assert main(argv, client=Fake(None)) == 0
    assert json.loads((out / "2026-11-18T18.json").read_text())["members"]
    assert main(argv, client=Fake("Auth111111111111111111111111111111111111111")) == 0
    assert json.loads((out / "2026-11-18T18.json").read_text())["members"] == []


def test_sample_appends_a_quote(tmp_path: Path) -> None:
    argv = [
        "--as-of",
        "2026-11-18T19:00:00+00:00",
        "--out",
        str(tmp_path / "out"),
        "--mode",
        "sample",
        "--samples",
        str(tmp_path / "samples"),
        "--mints-file",
        str(tmp_path / "mints.txt"),
        "--params",
        str(ROOT / "index" / "params.json"),
        "--overrides",
        str(ROOT / "index" / "overrides.json"),
    ]
    (tmp_path / "mints.txt").write_text(mint(1) + "\n")
    assert main(argv, client=Fake(None), discover=lambda *_a, **_k: []) == 0
    line = json.loads((tmp_path / "samples" / "2026-11-18.jsonl").read_text())
    assert line["mint"] == mint(1) and line["t"] == 1795028400
