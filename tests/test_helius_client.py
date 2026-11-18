"""Helius HTTP client against a fake transport. No network (#161)."""

from __future__ import annotations

import pytest

from adapters.helius_client import HeliusClient, http_transport

KEY = "unit-test-key"


def test_key_never_appears_in_errors_or_repr() -> None:
    def boom(method: str, url: str, body: dict | None) -> tuple[int, object]:
        raise OSError(url)

    client = HeliusClient(
        KEY,
        boom,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        rng=lambda: 0.5,
        rpc_interval=0,
        das_interval=0,
    )
    with pytest.raises(RuntimeError, match="rpc http 0") as caught:
        client.rpc("getAccountInfo", ["m"])
    assert KEY not in str(caught.value)
    assert KEY not in repr(client)
    with pytest.raises(ValueError, match="empty"):
        HeliusClient("  ")
    with pytest.raises(ValueError, match="host"):
        http_transport("GET", "https://evil.example/x", None)


def test_pairs_use_the_token_endpoint_and_retries() -> None:
    urls: list[str] = []
    calls = {"n": 0}

    def send(method: str, url: str, body: dict | None) -> tuple[int, object]:
        calls["n"] += 1
        urls.append(url.split("?", 1)[0])
        if calls["n"] == 1:
            return 429, None
        assert "/tokens/v1/solana/" in url
        return 200, [{"baseToken": {"address": "mint-a"}}]

    client = HeliusClient(
        KEY,
        send,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        rng=lambda: 0.5,
        dex_interval=0,
    )
    got = client.pairs(["mint-a"])
    assert got[0]["baseToken"]["address"] == "mint-a"  # type: ignore[index]
    assert calls["n"] == 2
    assert all("/search" not in url for url in urls)
    assert client.requests["dex"] == 2
