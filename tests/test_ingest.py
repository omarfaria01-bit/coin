"""adapters.ingest: strict types + sanity rules, every rejection with a clear message (#138)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapters.ingest import (
    IngestError,
    check_events,
    check_known_mints,
    check_prices,
    load_balances,
    solana_id,
)
from tools.run_epoch import EventIn, PriceIn

MINT = "FQvums9N2RLvft7qX7dBHCBDtZa8ngx5ywcPCB93LhJK"
OTHER_MINT = "So11111111111111111111111111111111111111112"


def _event(**overrides: object) -> EventIn:
    row = {"slot": 1, "ts": 100, "sig": "sig-a", "ix": 0, "kind": "buy", "dst": "wallet"}
    more = {"amount": 10, "lamports": 5, "fee_payer": "payer", **overrides}
    return EventIn(**{**row, **more})  # type: ignore[arg-type]


def test_event_amounts_and_types_are_strict() -> None:
    for bad in (1.5, True, "10", -1, 0):
        with pytest.raises(ValidationError, match="amount"):
            _event(amount=bad)
    with pytest.raises(ValidationError, match="lamports"):
        _event(lamports=-1)
    with pytest.raises(ValidationError, match="slot"):
        _event(slot=-1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        _event(memo="x")  # type: ignore[call-arg]


def test_mint_must_be_a_32_byte_base58_id() -> None:
    assert _event(mint=MINT).mint == MINT
    with pytest.raises(ValidationError, match="base58"):
        _event(mint="not a mint")
    with pytest.raises(ValueError, match="32 bytes"):
        solana_id("wallet", "abc")


def test_events_must_be_in_chain_order_with_monotonic_times() -> None:
    with pytest.raises(ValueError, match="non-decreasing"):
        check_events([_event(slot=2, ts=110, sig="a"), _event(slot=1, ts=120, sig="b")])
    with pytest.raises(ValueError, match="non-decreasing"):
        check_events([_event(slot=2, ts=120, sig="a"), _event(slot=3, ts=110, sig="b")])
    with pytest.raises(ValueError, match="in the same slot"):
        check_events([_event(slot=2, ts=120, sig="a"), _event(slot=2, ts=121, sig="b")])


def test_duplicate_tx_sigs_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate event"):
        check_events([_event(ix=0), _event(slot=2, ts=101, ix=0)])
    with pytest.raises(ValueError, match="duplicate tx sig"):
        check_events([_event(ix=0), _event(slot=2, ts=101, ix=1)])
    # one tx with two instructions in the same slot is valid
    assert len(check_events([_event(ix=0), _event(slot=1, ts=100, ix=1)])) == 2


def test_known_mint_allowlist() -> None:
    check_known_mints([_event(mint=MINT)], [MINT])
    with pytest.raises(ValueError, match="unknown mint"):
        check_known_mints([_event(mint=MINT)], [OTHER_MINT])
    with pytest.raises(ValueError, match="no known mints"):
        check_known_mints([_event(mint=MINT)], [])


def test_price_series_must_be_strictly_increasing() -> None:
    check_prices([PriceIn(ts=1, price=0.1), PriceIn(ts=2, price=0.2)])
    with pytest.raises(ValueError, match="strictly increasing"):
        check_prices([PriceIn(ts=1, price=0.1), PriceIn(ts=1, price=0.2)])
    with pytest.raises(ValueError, match="strictly increasing"):
        check_prices([PriceIn(ts=2, price=0.1), PriceIn(ts=1, price=0.2)])


def test_price_must_be_a_finite_positive_number() -> None:
    for bad in (0.0, -0.1, float("nan"), float("inf"), "0.1", True):
        with pytest.raises(ValidationError, match="price"):
            PriceIn(ts=1, price=bad)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="ts"):
        PriceIn(ts=1.5, price=0.1)  # type: ignore[arg-type]


def _book(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "balances.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_balances_load_and_derived_pending(tmp_path: Path) -> None:
    book = load_balances(
        _book(tmp_path, {"w1": {"earned_total": 10, "paid_total": 3, "pending": 7}})
    )
    assert book["w1"].pending == 7
    assert book["w1"].earned_total == book["w1"].paid_total + book["w1"].pending


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"earned_total": 10, "paid_total": 3, "pending": 8}, "earned_total must equal"),
        ({"earned_total": 10, "paid_total": 3, "pending": -7}, "greater than or equal to 0"),
        ({"earned_total": 10.0, "paid_total": 3, "pending": 7}, "valid integer"),
        ({"earned_total": 10, "paid_total": 3, "pending": 7, "extra": 1}, "Extra inputs"),
        ({"earned_total": 10, "paid_total": 3}, "Field required"),
    ],
)
def test_balances_reject_bad_rows(tmp_path: Path, row: object, message: str) -> None:
    with pytest.raises(IngestError, match=message) as exc:
        load_balances(_book(tmp_path, {"w1": row}))
    assert "balances.json" in str(exc.value) and "w1" in str(exc.value)
