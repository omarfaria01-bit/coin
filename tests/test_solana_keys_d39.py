"""D39 (#271 M3): off-curve (program-owned) owners are excluded; vectors checked with solders."""

from __future__ import annotations

from adapters.solana_keys import excluded_document, is_on_curve, rewards_excluded

KEYPAIRS = (
    "37dT3UyWkuWacX1MtiDviVQzyguSWmb3EPeEZKajoqV8",
    "9Dj14Mjt61QhvkYiwr1MDZoD7mEvxnnGLeVaJM64bqni",
    "74ajgZ83T5gptTp5oEc3wvwx41U3Ut2R4YAKzJxtkhXG",
)
PDAS = (  # find_program_address under the pump.fun AMM program
    "HHoAzV1V2w53WkXagBFak9zBntC3SXw8FAH5cdNu3S7c",
    "86WDUMSvQLBZHKX5eZcka3iegaSQLamBMePinfbnC6ZE",
    "C7MNHZkm4pN8pAhexCrPKMCmAVHkF8XzF8STmLqnxBJM",
)


def test_keypairs_on_curve_pdas_off_curve() -> None:
    assert all(is_on_curve(k) is True for k in KEYPAIRS)
    assert all(is_on_curve(p) is False for p in PDAS)
    assert is_on_curve("not-an-address") is None and is_on_curve("1111") is None


def test_excluded_list_has_reasons_and_dev_treasury() -> None:
    ex = rewards_excluded(
        [*KEYPAIRS, *PDAS], configured=["POOLX"], dev_wallets=[KEYPAIRS[0]], treasury=[KEYPAIRS[1]]
    )
    assert ex[KEYPAIRS[0]] == "dev" and ex[KEYPAIRS[1]] == "treasury"
    assert KEYPAIRS[2] not in ex and ex["POOLX"] == "configured"
    assert all(ex[p] == "program_owned_off_curve" for p in PDAS)
    doc = excluded_document(ex)
    assert doc["count"] == 6 and list(doc["excluded"]) == sorted(doc["excluded"])
