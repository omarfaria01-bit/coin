"""tests.adapters.solana_read: validation and read-only devnet RPC helper tests (#140)."""

from __future__ import annotations

import pytest

from adapters.solana_read import validate_devnet_url


def test_validate_devnet_url_accepts_devnet() -> None:
    assert validate_devnet_url("https://api.devnet.solana.com") == "https://api.devnet.solana.com"
    assert validate_devnet_url("https://rpc.devnet.solana.com") == "https://rpc.devnet.solana.com"
    assert validate_devnet_url("DEVNET.custom.rpc") == "DEVNET.custom.rpc"


def test_validate_devnet_url_refuses_non_devnet() -> None:
    non_devnet = [
        "https://api.mainnet-beta.solana.com",
        "https://localhost:8899",
        "http://127.0.0.1:8899",
        "https://example.com",
        "https://api.testnet.solana.com",
        "",
        "   ",
    ]
    for url in non_devnet:
        with pytest.raises(ValueError, match="Refusing non-devnet cluster URL"):
            validate_devnet_url(url)
