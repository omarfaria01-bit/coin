import json
from fractions import Fraction

from adapters.wallet_export import WalletInput, build_wallet_records, write_wallet_files
from engine.loyalty import loyalty_multiplier

SUPPLY = 1_000_000
A, B, C, D = "A" * 32, "B" * 32, "C" * 32, "D" * 32


def _records():
    wallets = [
        WalletInput(A, "ca", 10_000, 3 * 3600, (("GTA", 5, 1234),)),  # eligible, 3h -> 4x
        WalletInput(B, "cb", 10_000, 1800),  # < 1h: score 0
        WalletInput(C, "cc", 10_000, 2 * 3600),  # excluded
        WalletInput(D, "ca", 10_000, 5400),  # same cluster as A
    ]
    scores = {"ca": 100, "cb": 0, "cc": 0}  # excluded wallets are dropped before scoring (D39)
    bal = {"ca": 20_000, "cb": 10_000, "cc": 10_000}
    return build_wallet_records(
        wallets,
        scores=scores,
        cluster_balances=bal,
        total_supply=SUPPLY,
        excluded={C: "dev"},
        as_of="2026-11-19T06:00:00Z",
        cap=Fraction(1),
    )


def test_multiplier_is_engine_value():
    r = _records()
    for addr, secs in ((A, 3 * 3600), (B, 1800), (C, 7200), (D, 5400)):
        h = loyalty_multiplier(secs)
        assert r[addr]["multiplier"]["exact"] == f"{h.numerator}/{h.denominator}"
    assert r[A]["multiplier"]["decimal"] == "4.0000"
    assert r[B]["multiplier"]["decimal"] == "0.0000"


def test_eligibility_and_odds():
    r = _records()
    assert r[A]["eligible"] and r[D]["eligible"]
    assert not r[B]["eligible"] and r[B]["draw_odds"] == "0.000000000"
    assert not r[C]["eligible"] and r[C]["excluded_reason"] == "dev"
    # only cluster ca is in the draw; its two wallets split the whole odds equally by balance
    assert r[A]["draw_odds"] == r[D]["draw_odds"] == "0.500000000"
    assert r[A]["supply_share"] == "0.010000000"
    assert r[A]["accrued"] == [{"ticker": "GTA", "amount": "5", "usd": "12.34"}]


def test_write_atomic(tmp_path):
    n = write_wallet_files(_records(), tmp_path / "w")
    assert n == 4
    data = json.loads((tmp_path / "w" / f"{A}.json").read_text())
    assert data["address"] == A and data["schema"] == 1
    assert not list((tmp_path / "w").glob(".tmp-*"))


def test_long_hold_uses_the_ten_x_cap():
    wallets = [WalletInput(A, "ca", 10_000, 30 * 86_400)]
    r = build_wallet_records(
        wallets,
        scores={"ca": 1},
        cluster_balances={"ca": 10_000},
        total_supply=SUPPLY,
        excluded={},
        as_of="2026-11-19T06:00:00Z",
        cap=Fraction(1),
        min_holding_share=Fraction(1, 10**9),
    )
    assert r[A]["multiplier"]["exact"] == "10/1"
    assert r[A]["multiplier"]["decimal"] == "10.0000"


def test_unsafe_name_refused(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        write_wallet_files({"../x": {}}, tmp_path)
