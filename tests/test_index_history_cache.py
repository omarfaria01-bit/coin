"""Tests for adapters/index_history_cache.py and incremental mint history caching."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from adapters.index_history_cache import (
    fetch_mint_history_incremental,
    load_cache,
    save_cache,
)

TEST_MINT = "CacheMint11111111111111111111111111111111111"
AS_OF = 1_700_000_000


class FakeHeliusClient:
    def __init__(self, tx_pages: list[list[dict[str, object]]]) -> None:
        self.tx_pages = tx_pages
        self.requests = {"rpc": 0, "das": 0, "parsed": 0, "dex": 0}

    def history(
        self,
        address: str,
        *,
        start: int | None = None,
        end: int | None = None,
        sort: str = "desc",
        max_pages: int | None = None,
        limit: int = 100,
        stop_on_cached: set[str] | None = None,
    ) -> tuple[list[dict[str, object]], bool]:
        out: list[dict[str, object]] = []
        pages_to_fetch = len(self.tx_pages)
        if max_pages is not None:
            pages_to_fetch = min(pages_to_fetch, max_pages)

        for i in range(pages_to_fetch):
            self.requests["parsed"] += 1
            page = self.tx_pages[i]
            out.extend(page)
            if stop_on_cached is not None and page:
                oldest_sig = page[-1].get("signature")
                if isinstance(oldest_sig, str) and oldest_sig in stop_on_cached:
                    return out, False
        return out, False


def test_cache_miss_saves_and_returns_full_fetch(tmp_path: Path) -> None:
    page1 = [
        {"signature": "sig2", "block_time": AS_OF - 10},
        {"signature": "sig1", "block_time": AS_OF - 20},
    ]
    client = FakeHeliusClient([page1])

    txs, truncated = fetch_mint_history_incremental(
        client, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path
    )
    assert txs == page1
    assert truncated is False
    assert client.requests["parsed"] == 1

    cache_file = tmp_path / f"{TEST_MINT}.json"
    assert cache_file.is_file()
    cached = load_cache(TEST_MINT, tmp_path)
    assert cached is not None
    assert cached[0] == page1


def test_cache_hit_stops_early_and_drops_requests(tmp_path: Path) -> None:
    page2 = [{"signature": "sig3", "block_time": AS_OF - 5}]
    page1 = [
        {"signature": "sig2", "block_time": AS_OF - 10},
        {"signature": "sig1", "block_time": AS_OF - 20},
    ]

    client = FakeHeliusClient([page2, page1])

    txs1, _ = fetch_mint_history_incremental(client, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path)
    assert len(txs1) == 3
    reqs_run1 = client.requests["parsed"]

    client.requests["parsed"] = 0
    txs2, _ = fetch_mint_history_incremental(client, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path)
    assert txs2 == txs1
    assert client.requests["parsed"] < reqs_run1


def test_corrupt_cache_falls_back(tmp_path: Path) -> None:
    cache_file = tmp_path / f"{TEST_MINT}.json"
    cache_file.write_text("invalid json{{{", encoding="utf-8")

    page1 = [{"signature": "sig1", "block_time": AS_OF - 10}]
    client = FakeHeliusClient([page1])

    txs, _ = fetch_mint_history_incremental(client, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path)
    assert txs == page1
    assert client.requests["parsed"] == 1


def test_schema_mismatch_falls_back(tmp_path: Path) -> None:
    cache_file = tmp_path / f"{TEST_MINT}.json"
    bad_data = {"schema": 999, "mint": TEST_MINT, "transactions": []}
    cache_file.write_text(json.dumps(bad_data), encoding="utf-8")

    page1 = [{"signature": "sig1", "block_time": AS_OF - 10}]
    client = FakeHeliusClient([page1])

    txs, _ = fetch_mint_history_incremental(client, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path)
    assert txs == page1
    assert client.requests["parsed"] == 1


@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "signature": st.text(
                    min_size=5,
                    max_size=10,
                    alphabet=st.characters(whitelist_categories=(["Lu", "Ll", "Nd"])),
                ),
                "block_time": st.integers(min_value=AS_OF - 86_400, max_value=AS_OF),
            }
        ),
        min_size=1,
        max_size=20,
        unique_by=lambda x: x["signature"],
    )
)
@settings(max_examples=30, deadline=None)
def test_hypothesis_incremental_equals_full(
    txs: list[dict[str, object]],
) -> None:
    sorted_txs = sorted(txs, key=lambda t: (t["block_time"], t["signature"]), reverse=True)

    mid = max(1, len(sorted_txs) // 2)
    new_txs = sorted_txs[:mid]
    old_txs = sorted_txs[mid:]

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        client_inc = FakeHeliusClient([new_txs, old_txs])
        client_full = FakeHeliusClient([sorted_txs])

        full_res, _ = client_full.history(TEST_MINT, end=AS_OF)

        fetch_mint_history_incremental(client_inc, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path)
        client_inc.requests["parsed"] = 0
        res2, _ = fetch_mint_history_incremental(
            client_inc, TEST_MINT, as_of=AS_OF, cache_dir=tmp_path
        )

        assert {t["signature"] for t in res2} == {t["signature"] for t in full_res}


def test_failed_write_leaves_no_tmp(tmp_path: Path, monkeypatch) -> None:
    """#311: ENOSPC mid-write used to leave ~200 MB .tmp files behind on every retry."""
    import errno

    real_write = Path.write_text

    def boom(self, *args, **kwargs):
        real_write(self, "partial", encoding="utf-8")  # a partial file exists, then the disk fills
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_text", boom)
    rows = [{"signature": "a", "block_time": AS_OF}]
    save_cache(TEST_MINT, rows, False, AS_OF, cache_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_low_disk_skips_write(tmp_path: Path, monkeypatch) -> None:
    from adapters import index_history_cache as cache_mod

    monkeypatch.setattr(cache_mod, "MIN_FREE_BYTES", 10**18)  # more than any disk has free
    rows = [{"signature": "a", "block_time": AS_OF}]
    save_cache(TEST_MINT, rows, False, AS_OF, cache_dir=tmp_path)
    assert load_cache(TEST_MINT, tmp_path) is None


def test_cache_stores_slim_rows_and_default_cap(tmp_path: Path) -> None:
    from adapters.index_history_cache import DEFAULT_MAX_TOTAL_BYTES
    from tests.test_helius_slim import _fat_item

    rows = [_fat_item(i) for i in range(3)]
    save_cache(TEST_MINT, rows, False, AS_OF, cache_dir=tmp_path)
    loaded = load_cache(TEST_MINT, tmp_path)
    assert loaded is not None
    assert all("accountData" not in r["parsed"] for r in loaded[0])
    assert DEFAULT_MAX_TOTAL_BYTES == 1_000_000_000
