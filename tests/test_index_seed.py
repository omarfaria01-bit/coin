"""The persistent seed universe (issue #196): valid, unique, never the index coin."""

import json
from pathlib import Path

from tools.run_index import _valid, main

ROOT = Path(__file__).resolve().parent.parent


def _seeds() -> list[str]:
    out = []
    for line in (ROOT / "index/seed_mints.txt").read_text().splitlines():
        text = line.split("#", 1)[0].strip()
        if text:
            out.append(text)
    return out


def test_seed_file_is_valid_and_unique():
    seeds = _seeds()
    assert len(seeds) >= 90
    assert len(set(seeds)) == len(seeds)
    assert all(_valid(m) for m in seeds)
    params = json.loads((ROOT / "index/params.json").read_text())
    assert params.get("self_mint") not in seeds
    deny = {e["mint"] for e in json.loads((ROOT / "index/overrides.json").read_text())["deny"]}
    assert not deny & set(seeds)


def test_job_script_passes_seed_file():
    text = (ROOT / "ops/index-job/index-job.sh").read_text()
    assert "--mints-file" in text and "seed_mints.txt" in text
    assert "--discover-pages" in text


def test_sample_run_collects_seeds_when_discovery_is_empty(tmp_path):
    seen: list[list[str]] = []

    class Fake:
        requests = {"rpc": 0, "das": 0, "parsed": 0, "dex": 0}

    import tools.index_watch as watch

    orig = watch._mints
    watch._mints = lambda *a, **k: seen.append(orig(*a, **k)) or seen[-1]
    try:
        argv = [
            "--mode", "sample", "--as-of", "2026-11-18T05:00:00Z",
            "--params", str(ROOT / "index/params.json"),
            "--overrides", str(ROOT / "index/overrides.json"),
            "--samples", str(tmp_path / "s"), "--out", str(tmp_path / "o"),
            "--mints-file", str(ROOT / "index/seed_mints.txt"),
        ]  # fmt: skip
        main(argv, client=Fake(), discover=lambda *_a, **_k: [])
    finally:
        watch._mints = orig
    assert seen and set(_seeds()) <= set(seen[0])
