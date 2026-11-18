"""Incremental history cache (#247): same rows as a full fetch, fewer requests. No network."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adapters.helius_client import HeliusClient
from adapters.index_history_cache import HistoryCache, cached_history

PAGE = 5
WINDOW = 7 * 86_400


def _client(chain: list[dict]) -> HeliusClient:
    """Fake transport serving `chain` (newest first) in pages of PAGE, honouring time.lt."""

    def send(method: str, url: str, body: dict | None) -> tuple[int, object]:
        assert body is not None
        end = body.get("time", {}).get("lt", 10**12)
        rows = [r for r in chain if r["timestamp"] < end]
        i = int(body.get("paginationToken", "0"))
        page = rows[i : i + PAGE]
        more = i + PAGE < len(rows)
        return 200, {"data": page, "paginationToken": str(i + PAGE) if more else None}

    return HeliusClient(
        "k", send, sleep=lambda _s: None, clock=lambda: 0.0, rng=lambda: 0.5,
        das_interval=0, max_history_pages=50,
    )  # fmt: skip


def _chain(n: int, start: int = 0) -> list[dict]:
    return [{"signature": f"s{i}", "timestamp": 1000 + i} for i in range(start + n - 1, -1, -1)]


def test_second_run_costs_under_a_quarter(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path)
    first = _client(_chain(100))
    rows1, _ = cached_history(first, cache, "MINT", as_of=5000, max_age=WINDOW)
    second = _client(_chain(103))  # 3 new txs since
    rows2, trunc = cached_history(second, cache, "MINT", as_of=5100, max_age=WINDOW)
    full, _ = _client(_chain(103)).history("MINT", end=5100)
    assert rows2 == full and not trunc and len(rows1) == 100
    assert first.requests["parsed"] == 20
    assert second.requests["parsed"] == 1
    assert second.requests["parsed"] < 0.25 * first.requests["parsed"]


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.integers(0, 60), st.integers(0, 30))
def test_incremental_equals_full(tmp_path_factory, old_n: int, added: int) -> None:  # noqa: ANN001
    cache = HistoryCache(tmp_path_factory.mktemp("c"))
    cached_history(_client(_chain(old_n)), cache, "M", as_of=5000, max_age=WINDOW)
    chain = _chain(old_n + added)
    got, _ = cached_history(_client(chain), cache, "M", as_of=5100, max_age=WINDOW)
    want, _ = _client(chain).history("M", end=5100)
    assert got == want


def test_corrupt_or_stale_cache_falls_back_to_full(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path)
    chain = _chain(30)
    want, _ = _client(chain).history("M", end=5100)
    for junk in ("{not json", '{"schema": 99}', '{"schema":1,"address":"M","as_of":1,"rows":[1]}'):
        (tmp_path / "M.json").write_text(junk)
        c = _client(chain)
        got, _ = cached_history(c, cache, "M", as_of=5100, max_age=WINDOW)
        assert got == want and c.requests["parsed"] == 6
    # valid but older than the window: not used
    cached_history(_client(chain), cache, "M", as_of=5000, max_age=WINDOW)
    c = _client(chain)
    cached_history(c, cache, "M", as_of=5000 + WINDOW + 1, max_age=WINDOW)
    assert c.requests["parsed"] == 6
    # clock went backwards: not used
    c = _client(chain)
    cached_history(c, cache, "M", as_of=4000, max_age=WINDOW)
    assert c.requests["parsed"] == 6


def test_capped_history_is_never_cached(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path)
    c = _client(_chain(100))
    c.max_history_pages = 3
    _, trunc = cached_history(c, cache, "M", as_of=5000, max_age=WINDOW)
    assert trunc and not (tmp_path / "M.json").exists()


def test_unsafe_address_is_not_a_path(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path / "c")
    cached_history(_client(_chain(3)), cache, "../x", as_of=5000, max_age=WINDOW)
    assert not (tmp_path / "x.json").exists()
