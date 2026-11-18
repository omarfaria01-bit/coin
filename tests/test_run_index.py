"""tools/run_index.py writes one hour from a trailing window and holds missing data."""

from __future__ import annotations

import json
from pathlib import Path

import base58

from index.filters import Metrics
from index.params import IndexParams, Overrides
from index.select import canonical_json, run_index
from tools.run_index import main

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
AS_OF = "2026-11-18T19:00:00+00:00"
UNIX = 1795028400  # 2026-11-18T19:00:00Z


class Fake:
    requests = {"rpc": 0, "das": 0, "parsed": 0, "dex": 0}


def mint(i: int) -> str:
    return base58.b58encode(bytes([i]) * 32).decode()


def good(i: int = 1, **kw: object) -> Metrics:
    base = dict(
        mint=mint(i),
        ticker="GTA6",
        name="Vice City",
        coverage=1.0,
        age_hours=30.0,
        liquidity_usd=120_000.0,
        mc_usd=1_000_000.0,
        top10_pct=20.0,
        total_fees_sol=40.0,
        window_fees_sol=12.0,
        bundle_pct=2.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=500,
        independent_traders=500,
        roundtrip_share=0.0,
        volume_wallets=100,
        median_trade_sol=0.1,
        volume_usd=100_000.0,
    )
    base.update(kw)
    return Metrics(**base)  # type: ignore[arg-type]


def _run(
    tmp: Path,
    measure,
    samples: Path | None = None,
    mints: str | None = None,
    extra: tuple[str, ...] = (),
    self_mint: str | None = None,
) -> int:
    params = tmp / "params.json"
    hourly = P.model_copy(update={"rebalance_hours": 1, "self_mint": self_mint}).model_dump(
        mode="json"
    )
    params.write_text(json.dumps(hourly))
    argv = [
        "--as-of",
        AS_OF,
        "--out",
        str(tmp / "out"),
        "--params",
        str(params),
        "--overrides",
        str(ROOT / "index" / "overrides.json"),
        "--samples",
        str(samples or tmp / "none"),
    ]
    if mints:
        (tmp / "mints.txt").write_text(mints + "\n")
        argv.extend(["--mints-file", str(tmp / "mints.txt")])
    argv.extend(extra)
    return main(argv, client=Fake(), measure=measure, discover=lambda *_a, **_k: [])


def test_missing_key_does_not_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    assert main(["--as-of", AS_OF, "--out", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()


def test_window_spans_the_previous_utc_day_and_names_the_hour(tmp_path: Path) -> None:
    seen: dict = {}

    def measure(_client, _mints, **kw):
        seen["start"] = kw["window_start"]
        seen["times"] = {row.t for row in kw["samples"]}
        return [good()]

    samples = tmp_path / "samples"
    samples.mkdir()

    def point(t, v):
        row = {"mint": mint(1), "t": t, "mc_usd": v, "liquidity_usd": v, "volume_usd": v}
        return json.dumps(row)

    prior = point(UNIX - 80_000, 1) + "\n" + point(UNIX - 90_000, 9) + "\n"
    (samples / "2026-11-17.jsonl").write_text(prior)
    (samples / "2026-11-18.jsonl").write_text(point(UNIX - 100, 2) + "\n")
    assert _run(tmp_path, measure, samples, mint(1)) == 0
    assert seen["start"] == UNIX - 24 * 3600
    assert seen["times"] == {UNIX - 80_000, UNIX - 100}
    assert (tmp_path / "out" / "2026-11-18T19.json").is_file()


def test_missing_hour_keeps_the_member_and_a_crash_keeps_the_file(tmp_path: Path) -> None:
    hourly = P.model_copy(update={"rebalance_hours": 1})
    out = tmp_path / "out"
    out.mkdir()
    previous = run_index([good()], [], hourly, Overrides(), "2026-11-18T18:00:00Z", "abc")
    (out / "2026-11-18T18.json").write_bytes(canonical_json(previous))
    assert _run(tmp_path, lambda *_a, **_k: [good(coverage=0.0)]) == 0
    payload = json.loads((out / "2026-11-18T19.json").read_text())
    assert [m["mint"] for m in payload["members"]] == [mint(1)]
    assert payload["data_hold"] == [mint(1)]

    def boom(*_a, **_k):
        raise RuntimeError("helius down")

    assert _run(tmp_path, boom) == 1
    assert json.loads((out / "2026-11-18T19.json").read_text())["data_hold"] == [mint(1)]


def test_official_refuses_without_self_mint_and_writes_nothing(tmp_path: Path) -> None:
    assert _run(tmp_path, lambda *_a, **_k: [good()], extra=("--official",)) == 3
    assert not (tmp_path / "out").exists()


def test_official_refuses_insufficient_data_and_keeps_previous_file(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "2026-11-18T18.json").write_text("{}")
    bad = lambda *_a, **_k: [good(coverage=0.0)]  # noqa: E731
    assert _run(tmp_path, bad, mints=mint(1), extra=("--official",), self_mint=mint(9)) == 3
    assert sorted(p.name for p in out.iterdir()) == ["2026-11-18T18.json"]


def test_official_with_self_mint_and_full_data_writes_a_file(tmp_path: Path) -> None:
    assert _run(tmp_path, lambda *_a, **_k: [good()], extra=("--official",), self_mint=mint(9)) == 0
    assert (tmp_path / "out" / "2026-11-18T19.json").is_file()
