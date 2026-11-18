"""The persistent seed universe (issue #196): valid, unique, never the index coin."""

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from index.filters import Metrics, candidate_status, first_failed_filter
from index.params import IndexParams, Overrides
from index.select import run_index
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


@settings(max_examples=50)
@given(
    st.sampled_from(_seeds()),
    st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
)
def test_seeded_mints_never_bypass_safety_filters(
    mint: str, age_hours: float, liquidity_usd: float
) -> None:
    """Hypothesis test: seeded mints from seed_mints.txt never bypass safety filters (#232)."""
    params = IndexParams.model_validate(json.loads((ROOT / "index/params.json").read_text()))
    overrides = Overrides()

    m = Metrics(
        mint=mint,
        ticker="NOTGTA",
        name="Random Coin",
        coverage=1.0,
        age_hours=age_hours,
        liquidity_usd=liquidity_usd,
        mc_usd=1_500_000.0,
        top10_pct=20.0,
        total_fees_sol=40.0,
        window_fees_sol=12.0,
        bundle_pct=3.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=900,
        independent_traders=900,
        roundtrip_share=0.0,
        volume_wallets=100,
        median_trade_sol=0.1,
        volume_usd=600_000.0,
    )

    status = candidate_status(m, params, overrides)
    if status is None:
        fail_filter = first_failed_filter(m, params)
        assert fail_filter is not None, (
            f"Seeded mint {mint} bypassed safety filters with failing metrics!"
        )
    else:
        assert status in {"no_keyword", "weak_keyword", "denied", "self"}

    res = run_index(
        candidates=[m],
        prev_members=[],
        params=params,
        overrides=overrides,
        as_of="2026-11-18T06:00:00Z",
        code_commit="abc",
    )
    assert not any(mem["mint"] == mint for mem in res["members"])
    assert any(exc["mint"] == mint for exc in res["excluded"]) or len(res["members"]) == 0
