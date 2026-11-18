"""tests.adapters.solana_read: validation and read-only devnet RPC helper tests (#140)."""

from __future__ import annotations

import pytest

from adapters.solana_read import validate_devnet_url


def test_validate_devnet_url_accepts_devnet() -> None:
    assert validate_devnet_url("https://api.devnet.solana.com") == "https://api.devnet.solana.com"
    assert validate_devnet_url("https://rpc.devnet.solana.com") == "https://rpc.devnet.solana.com"
    assert validate_devnet_url("https://DEVNET.custom.rpc") == "https://DEVNET.custom.rpc"


def test_validate_devnet_url_refuses_non_devnet() -> None:
    non_devnet = [
        "https://api.mainnet-beta.solana.com",
        "https://localhost:8899",
        "http://127.0.0.1:8899",
        "https://example.com",
        "https://mainnet.example.com/devnet",
        "https://api.mainnet-beta.solana.com/?cluster=devnet",
        "https://api.testnet.solana.com",
        "",
        "   ",
    ]
    for url in non_devnet:
        with pytest.raises(ValueError, match="Refusing non-devnet cluster URL"):
            validate_devnet_url(url)


def test_fetch_mint_history_skips_and_counts_parse_failures(monkeypatch, caplog) -> None:
    from adapters import solana_read as sr
    from adapters.parse_tx import ParseError

    monkeypatch.setattr(sr, "fetch_signatures", lambda *a, **k: ["bad", "good"])
    monkeypatch.setattr(sr, "fetch_transaction", lambda _u, sig: {"sig": sig})

    def fake_parse(tx, mint):
        if tx["sig"] == "bad":
            raise ParseError("boom")
        return ("EV",), ("SOL",)

    monkeypatch.setattr(sr, "parse_tx", fake_parse)
    with caplog.at_level("WARNING"):
        evs, sols = sr.fetch_mint_history("https://x", "M")
    assert evs == ("EV",) and sols == ("SOL",)
    assert "skipped 1 of 2" in caplog.text


def test_fetch_mint_history_propagates_unexpected_errors(monkeypatch) -> None:
    from adapters import solana_read as sr

    monkeypatch.setattr(sr, "fetch_signatures", lambda *a, **k: ["s"])
    monkeypatch.setattr(sr, "fetch_transaction", lambda *a: {"x": 1})

    def boom(tx, mint):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(sr, "parse_tx", boom)
    with pytest.raises(RuntimeError):
        sr.fetch_mint_history("https://x", "M")
