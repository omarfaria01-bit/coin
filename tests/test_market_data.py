"""adapters/market_data.py + tools/run_index.py: pure aggregation and offline CLI (#161)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters import market_data as md
from index.params import IndexParams, OverrideEntry, Overrides
from index.select import canonical_json
from tools.run_index import collect, parse_iso, previous_members, run

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "index"
PARAMS = IndexParams.model_validate_json((ROOT / "index" / "params.json").read_text())
A = "G9ZMir6uh66Y7viPkXAy7myA9jjE4T1YgheVUmGDpump"
B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
C = "So11111111111111111111111111111111111111112"
END = 1_795_024_800  # 2026-11-18T18:00:00Z


def _json(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _opener(mapping: dict[str, object]):
    def opener(url: str):
        for part, payload in mapping.items():
            if part in url:
                return payload
        raise AssertionError(f"unexpected URL {url}")

    return opener


# ------------------------------------------------------------------ DexScreener


def test_search_keeps_only_solana_pairs() -> None:
    pairs = md.search("GTA", opener=_opener({"dex/search": _json("dex_search.json")}))
    assert {p["baseToken"]["symbol"] for p in pairs} == {"GTA", "VIBE"}


def test_tokens_batches_at_thirty_addresses() -> None:
    urls: list[str] = []

    def opener(url: str):
        urls.append(url)
        return []

    md.tokens([f"Mint{i}" for i in range(31)], opener=opener)
    assert len(urls) == 2
    assert len(urls[0].rsplit("/", 1)[-1].split(",")) == 30
    assert len(urls[1].rsplit("/", 1)[-1].split(",")) == 1


def test_discover_keeps_strong_hits_and_allow_entries() -> None:
    search = _json("dex_search.json")
    allowed = OverrideEntry(mint=C, reason="kiwi allowed it", issue=161)
    overrides = Overrides(allow=(allowed,))
    by_mint = md.discover(
        PARAMS,
        overrides,
        opener=_opener({"dex/search": search, "tokens": _json("dex_tokens.json")}),
    )
    assert A in by_mint  # "Good To Ape GTA"
    assert C in by_mint  # allow entry, no strong keyword needed
    assert B not in by_mint  # "Vibe Cat VIBE": VI has letters on both sides
    assert "ethereum" not in {p["chainId"] for p in by_mint.values()}


def test_market_record_reads_dexscreener_fields() -> None:
    pair = _json("dex_search.json")["pairs"][0]
    rec = md.market_record(pair, END)
    assert rec["mint"] == A and rec["ticker"] == "GTA"
    assert rec["liquidity_usd"] == 34969.47
    assert rec["market_cap_usd"] == 117264.0
    assert rec["volume_h24_usd"] == 439422.38
    assert rec["pair_created_at"] == 1794720632000


# ------------------------------------------------------------------ RPC + Helius


def _rpc_poster(method: str, params: list):
    if method == "getTokenLargestAccounts":
        wallets = [{"address": f"Wallet{i}", "amount": "5"} for i in range(10)]
        others = [
            {"address": "Vault", "amount": "20"},
            {"address": "Burn", "amount": "20"},
            {"address": "Hub", "amount": "10"},
        ]
        return {"result": {"value": wallets + others}}
    if method == "getTokenAccountsByOwner":
        accounts = [
            {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": "25"}}}}}},
            {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": "0"}}}}}},
        ]
        return {"result": {"value": accounts}}
    if method == "getAccountInfo":
        address = params[0]
        if address == "Vault":
            data = {"data": {"parsed": {"info": {"owner": "VaultAuthority"}}}}
            return {"result": {"value": data}}
        if address == "VaultAuthority":
            return {"result": {"value": {"owner": next(iter(md.POOL_PROGRAMS))}}}
        parsed = {
            "info": {"mintAuthority": None, "freezeAuthority": None, "supply": "1000"},
            "type": "mint",
        }
        return {
            "result": {
                "value": {
                    "owner": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
                    "data": {"program": "spl-token-2022", "parsed": parsed},
                }
            }
        }
    raise AssertionError(f"unexpected RPC method {method}")


def _poster(url: str, payload: dict):
    assert url.startswith("https://")
    return _rpc_poster(payload["method"], payload["params"])


def test_mint_facts_reads_authorities_and_program() -> None:
    facts = md.mint_facts("https://rpc.invalid", A, END, poster=_poster)
    assert facts is not None
    assert facts["mint_authority_revoked"] is True
    assert facts["freeze_authority_revoked"] is True
    assert facts["token_program"] == "spl-token-2022"


def test_mint_facts_is_none_on_a_malformed_mint_account() -> None:
    def poster(url: str, payload: dict):
        return {"result": {"value": {"data": {"parsed": {"info": {}}}}}}

    assert md.mint_facts("https://rpc.invalid", A, END, poster=poster) is None


def test_top10_excludes_burn_hub_and_pool_vault() -> None:
    pct = md.top10_pct(
        "https://rpc.invalid",
        A,
        100,
        hubs=frozenset({"Hub"}),
        excluded=frozenset({"Burn"}),
        poster=_poster,
    )
    assert pct == 50.0  # ten 5% wallets kept; vault, hub and burn removed


def test_top10_is_none_when_fewer_than_ten_accounts_remain() -> None:
    def poster(url: str, payload: dict):
        if payload["method"] == "getTokenLargestAccounts":
            return {"result": {"value": [{"address": f"W{i}", "amount": "1"} for i in range(9)]}}
        return {"result": {"value": None}}

    assert md.top10_pct("https://rpc.invalid", A, 100, poster=poster) is None


def test_top10_is_none_without_rpc_data() -> None:
    assert md.top10_pct("https://rpc.invalid", A, 100, poster=lambda u, p: {"result": None}) is None


def test_dev_pct_sums_the_creator_token_accounts() -> None:
    assert md.dev_pct("https://rpc.invalid", A, "Creator", 1000, poster=_poster) == 2.5


def test_creator_is_the_fee_payer_of_the_earliest_transaction() -> None:
    def item(payer: str, ts: int, signature: str, status: str = "OK") -> dict:
        return {
            "signature": signature,
            "parserStatus": status,
            "parsed": {"feePayer": payer, "blockTime": ts},
        }

    history = [
        item("later", 300, "b"),
        item("earliest", 100, "a"),
        item("failed", 50, "c", status="ERROR"),
    ]
    assert md.creator_from_history(history) == "earliest"
    assert md.creator_from_history([]) is None


def test_unique_traders_counts_distinct_swap_payers_in_window() -> None:
    def item(payer: str, kind: str, ts: int, status: str = "OK") -> dict:
        return {
            "parserStatus": status,
            "parsed": {"summary": {"type": kind}, "feePayer": payer, "blockTime": ts},
        }

    history = [
        item("w1", "swap", 100),
        item("w1", "swap", 110),
        item("w2", "swap", 120),
        item("w3", "transfer", 130),  # not a swap
        item("w4", "swap", 99),  # before the window
        item("w5", "swap", 140, status="ERROR"),  # failed transaction
    ]
    assert md.unique_traders(history, since_ts=100, until_ts=130) == 2


# ------------------------------------------------------------------ aggregation


def test_aggregate_means_medians_coverage_and_sources() -> None:
    samples = md.read_samples(str(FIX / "samples.jsonl"))
    metrics = {m.ticker: m for m in md.aggregate(samples, END - 3600, END, PARAMS)}
    a = metrics["GTA"]
    assert a.coverage == 1.0
    assert a.age_hours == 12.0
    assert a.liquidity_usd == 80_000.0
    assert a.mc_usd == 1_000_000.0
    assert a.volume_usd == 200_000.0
    assert a.top10_pct == 21.0  # median of 20 and 22
    assert a.dev_pct == 2.0
    assert a.total_fees_sol == 20.0 and a.window_fees_sol == 15.0
    assert a.unique_traders == 300
    assert a.mint_authority_revoked is True and a.freeze_authority_revoked is True
    assert a.bundle_pct == 0.0 and a.creator_launches_7d == 2
    assert a.sources["mc_usd"].startswith("dexscreener@")
    assert a.sources["unique_traders"].startswith("helius@")


def test_aggregate_missing_metric_stays_none() -> None:
    metrics = {
        m.ticker: m
        for m in md.aggregate(md.read_samples(str(FIX / "samples.jsonl")), END - 3600, END, PARAMS)
    }
    c = metrics["GTA6"]
    assert c.mc_usd is None and c.volume_usd is None and c.top10_pct is None
    b = metrics["GTAVI"]
    assert b.age_hours == 0.5
    assert b.coverage == pytest.approx(4 / 6, abs=1e-6)  # 4 of 6 five-minute buckets
    assert b.top10_pct is None


def test_aggregate_treats_nan_and_infinity_as_missing() -> None:
    rows = [
        {
            "kind": "market",
            "ts": END,
            "mint": A,
            "ticker": "GTA",
            "name": "",
            "description": "",
            "market_cap_usd": float("nan"),
            "liquidity_usd": float("inf"),
            "volume_h24_usd": 1.0,
            "pair_created_at": (END - 3600) * 1000,
        }
    ]
    (m,) = md.aggregate(rows, END - 3600, END, PARAMS)
    assert m.mc_usd is None and m.liquidity_usd is None


def test_aggregate_ignores_samples_outside_the_window() -> None:
    rows = [
        {
            "kind": "market",
            "ts": END - 7200,
            "mint": A,
            "ticker": "GTA",
            "market_cap_usd": 1.0,
            "liquidity_usd": 1.0,
        }
    ]
    assert md.aggregate(rows, END - 3600, END, PARAMS) == []


def test_aggregate_rejects_bad_samples() -> None:
    with pytest.raises(ValueError):
        md.aggregate([{"kind": "nope", "mint": A, "ts": END}], END - 3600, END, PARAMS)
    with pytest.raises(ValueError):
        md.aggregate([{"kind": "market", "mint": A, "ts": "yesterday"}], END - 3600, END, PARAMS)
    with pytest.raises(ValueError):
        md.aggregate([], END, END, PARAMS)


# ------------------------------------------------------------------ CLI


def _run(tmp_path: Path, **kwargs):
    params = FIX / "params_small.json"
    return run(
        as_of="2026-11-18T18:00:00Z",
        out_dir=tmp_path / "out",
        samples_path=FIX / "samples.jsonl",
        params_path=params,
        overrides_path=FIX / "overrides_empty.json",
        offline=True,
        code_commit="abc123",
        **kwargs,
    )


def test_run_index_offline_writes_canonical_dry_run(tmp_path: Path) -> None:
    path = _run(tmp_path, skip_filters=("F4",))
    assert path.name == "2026-11-18.dryrun.json"
    raw = path.read_bytes()
    data = json.loads(raw)
    assert raw == canonical_json(data) + b"\n"
    assert data["dry_run"] is True and data["skipped_filters"] == ["F4"]
    assert data["code_commit"] == "abc123"
    assert data["members"][0]["mint"] == A  # passes every filter once F4 is skipped
    assert data["members"][0]["weight_bps"] == 10_000
    excluded = {e["mint"]: e["reason"] for e in data["excluded"]}
    assert excluded == {B: "insufficient_data", C: "insufficient_data"}


def test_run_index_offline_without_skip_marks_f4_missing(tmp_path: Path) -> None:
    path = _run(tmp_path, skip_filters=())
    data = json.loads(path.read_bytes())
    assert path.name == "2026-11-18.json"
    assert data["dry_run"] is False and data["skipped_filters"] == []
    assert data["members"] == []
    assert {e["reason"] for e in data["excluded"]} == {"F4", "insufficient_data"}


def test_previous_members_uses_newest_older_output(tmp_path: Path) -> None:
    out = tmp_path
    (out / "2026-11-17.json").write_text(json.dumps({"members": [{"mint": A}]}))
    assert previous_members(out, "2026-11-18.dryrun.json") == [A]
    assert previous_members(out, "2026-11-17.json") == []
    (out / "broken.json").write_text("{not json")
    assert previous_members(out, "2026-11-18.json") == [A]


def test_collect_appends_market_and_launch_records(tmp_path: Path) -> None:
    path = tmp_path / "samples.jsonl"
    params = IndexParams.model_validate_json((FIX / "params_small.json").read_text())
    writes = collect(
        path,
        END,
        params,
        Overrides(),
        rpc_url="https://rpc.invalid",
        helius_key=None,
        holders=False,
        fetch=_opener({"dex/search": _json("dex_search.json"), "tokens": _json("dex_tokens.json")}),
        poster=_poster,
    )
    records = md.read_samples(str(path))
    assert writes == len(records) > 0
    market = [r for r in records if r["kind"] == "market"]
    launch = [r for r in records if r["kind"] == "launch"]
    assert {r["mint"] for r in market} == {A}
    assert {r["mint"] for r in launch} == {A}
    assert market[0]["liquidity_usd"] == 80000.0  # the more liquid GTA pair
    assert launch[0]["freeze_authority_revoked"] is True


def test_parse_iso_requires_a_real_timestamp() -> None:
    assert parse_iso("2026-11-18T18:00:00Z") == END
    assert parse_iso("2026-11-18") == END - 18 * 3600
    with pytest.raises(ValueError):
        parse_iso("yesterday")
