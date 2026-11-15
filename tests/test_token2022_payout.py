"""Token-2022 payout path: mint parsing, fee math, epoch schedule and ATA vectors."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from adapters.token2022 import (
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    TransferFee,
    associated_token_address,
    parse_mint_account,
    plan_payouts,
)

FIXTURES = Path(__file__).parent / "fixtures" / "token2022"
M22 = "FQvums9N2RLvft7qX7dBHCBDtZa8ngx5ywcPCB93LhJK"
MLEG = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MBARE = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
W1, W2, W3 = (
    "GdocRWkjKvKKipjf4LvEDui287yGXCinGSbWzRBAL2Av",
    "Cfct9oGYqKcbvPcaAuqK9Xwgt3N7W51RjiKPP3xNwSJ",
    "Hd871zgBusnaxDBHU3GJkphqYVm1bwzYDkCwLX8F3GB8",
)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def with_data(doc: dict, data: bytes, owner: str | None = None) -> dict:
    value = {**doc["result"]["value"], "data": [base64.b64encode(data).decode(), "base64"]}
    return {"result": {**doc["result"], "value": {**value, "owner": owner or value["owner"]}}}


@pytest.fixture(scope="module")
def fee_mint():
    return parse_mint_account(load("mint_t22_transfer_fee.json"), address=M22)


def test_parse_mints_and_epoch_schedule(fee_mint) -> None:
    assert (fee_mint.program_id, fee_mint.decimals) == (TOKEN_2022_PROGRAM, 6)
    config = fee_mint.transfer_fee
    assert config is not None
    assert [(f.epoch, f.maximum_fee, f.basis_points) for f in (config.older, config.newer)] == [
        (0, 1_000_000, 250),
        (500, 500_000, 500),
    ]
    assert [config.for_epoch(epoch).basis_points for epoch in (0, 499, 500)] == [250, 250, 500]
    legacy = parse_mint_account(load("mint_legacy.json"), address=MLEG)
    bare = parse_mint_account(load("mint_t22_bare.json"), address=MBARE)
    assert (legacy.program_id, legacy.decimals, legacy.transfer_fee) == (TOKEN_PROGRAM, 9, None)
    assert (bare.program_id, bare.decimals, bare.transfer_fee) == (TOKEN_2022_PROGRAM, 9, None)
    doc = load("mint_t22_transfer_fee.json")
    raw = base64.b64decode(doc["result"]["value"]["data"][0])
    bad = [
        (raw[:165] + b"\x02" + raw[166:], "account type 2"),
        (raw[:120], "expected 82 or"),
        (raw + raw[-112:], "duplicate extension 1"),
    ]
    for data, error in bad:
        with pytest.raises(ValueError, match=error):
            parse_mint_account(with_data(doc, data), address=M22)
    with pytest.raises(ValueError, match="exactly 82 bytes"):
        parse_mint_account(with_data(doc, raw, owner=TOKEN_PROGRAM), address=M22)


def test_fee_math_matches_official_vectors_and_is_minimal() -> None:
    fee = TransferFee(0, 5_000, 1)
    assert [fee.fee(n) for n in (0, 1, 9_999, 10_000, 10_001)] == [0, 1, 1, 1, 2]
    assert fee.fee(5_000 * 10_000) == 5_000  # capped at maximum_fee
    assert fee.pre_fee_amount(1) == 2  # one-unit minimum fee
    assert fee.pre_fee_amount(5_000 * 10_000 - 5_000) == 5_000 * 10_000  # at the cap
    for bps, cap in ((1, 5_000), (250, 1_000_000), (9_999, 10**9)):
        schedule = TransferFee(0, cap, bps)
        for net in (1, 2, 333, 10_000, 1_000_000, 10**9):
            gross = schedule.pre_fee_amount(net)
            assert gross - schedule.fee(gross) == net
            assert schedule.fee(gross) == min(-(-gross * bps // 10_000), cap)
            if gross > net:
                assert (gross - 1) - schedule.fee(gross - 1) < net


def test_ata_derivation_matches_reference_vectors() -> None:
    for case in load("ata_vectors.json")["ata_cases"]:
        assert (
            associated_token_address(case["owner"], case["mint"], case["token_program"])
            == (case["ata"])
        )


def test_plan_pays_net_and_records_the_fee(fee_mint) -> None:
    payouts = {W3: 10_000_000, W1: 333, W2: 1_000_000}
    plan = plan_payouts(payouts, fee_mint, epoch=500)
    by_wallet = {leg.wallet: leg for leg in plan.legs}
    assert [(by_wallet[w].gross, by_wallet[w].fee) for w in (W1, W2, W3)] == [
        (351, 18),
        (1_052_632, 52_632),
        (10_500_000, 500_000),
    ]
    for leg in plan.legs:
        assert leg.gross - leg.fee == leg.received == leg.net
        assert leg.ata == associated_token_address(leg.wallet, M22, TOKEN_2022_PROGRAM)
    assert plan.ledger_credits() == payouts
    legacy = plan_payouts(
        {W1: 1_000_000},
        parse_mint_account(load("mint_legacy.json"), address=MLEG),
        epoch=0,
        expected_decimals=9,
    )
    assert (legacy.legs[0].gross, legacy.legs[0].fee) == (1_000_000, 0)
    assert legacy.legs[0].ata == associated_token_address(W1, MLEG, TOKEN_PROGRAM)


def test_plan_rejects_wrong_decimals_and_bad_amounts(fee_mint) -> None:
    with pytest.raises(ValueError, match="has 6 decimals, expected 9"):
        plan_payouts({W1: 1}, fee_mint, epoch=0, expected_decimals=9)
    with pytest.raises(ValueError, match="base58 pubkey"):
        plan_payouts({"not-a-wallet": 1}, fee_mint, epoch=0)
