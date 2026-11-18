"""#311: slim_item keeps exactly what normalize_transaction reads. No network."""

from __future__ import annotations

import copy
import json

from hypothesis import given, settings
from hypothesis import strategies as st

from adapters.helius_parse import PUMP_PROGRAM, normalize_transaction, slim_item
from tests.test_helius_parse import MINT, TRADER, _item


def _fat_item(i: int = 0) -> dict:
    """_item() plus the bulky fields a Parsed Events row really carries (account data, other
    programs' instructions with inner calls, logs, long descriptions)."""
    item = _item()
    item["signature"] = f"sig{i}"
    p = item["parsed"]
    p["summary"]["description"] = "x" * 400
    p["accountData"] = [
        {"account": f"Acc{k:040d}", "nativeBalanceChange": -k, "tokenBalanceChanges": []}
        for k in range(30)
    ]
    p["logMessages"] = [f"Program log: step {k} " + "y" * 60 for k in range(40)]
    p["instructions"].extend(
        {
            "programId": "Other1111111111111111111111111111111111111",
            "instructionName": "swap",
            "decoded": {"args": {"amount": k}, "accounts": [{"name": "a", "pubkey": "p" * 44}] * 8},
            "innerInstructions": [{"programId": "Tok", "data": "z" * 120}] * 6,
        }
        for k in range(12)
    )
    p["tokenTransfers"][0]["tokenStandard"] = "Fungible"
    p["tokenTransfers"][0]["fromTokenAccount"] = "f" * 44
    p["nativeTransfers"][0]["note"] = "extra"
    return item


def test_slim_keeps_normalized_result_and_create() -> None:
    for item in (_item(), _fat_item()):
        before = normalize_transaction(copy.deepcopy(item))
        assert normalize_transaction(slim_item(item)) == before
        assert before is not None and before["creates"][0]["mint"] == MINT


def test_slim_is_idempotent_and_keeps_cache_keys() -> None:
    once = slim_item(_fat_item())
    assert slim_item(once) == once
    plain = {"signature": "s", "block_time": 5, "junk": 1}
    assert slim_item(plain) == {"signature": "s", "block_time": 5}
    assert slim_item("not a dict") == "not a dict"


def test_slim_drops_non_create_instructions_only() -> None:
    p = slim_item(_fat_item())["parsed"]
    assert [ix["instructionName"] for ix in p["instructions"]] == ["create"]
    assert p["instructions"][0]["programId"] == PUMP_PROGRAM
    assert "uri" not in p["instructions"][0]["decoded"]["args"]
    assert "accountData" not in p and "logMessages" not in p


def test_payload_size_before_after() -> None:
    rows = [_fat_item(i) for i in range(100)]
    before = len(json.dumps(rows, separators=(",", ":")))
    after = len(json.dumps([slim_item(r) for r in rows], separators=(",", ":")))
    print(f"100 rows: before {before} bytes, after {after} bytes ({after / before:.1%})")
    assert after < before / 5


_values = st.one_of(st.none(), st.integers(-5, 10**12), st.text(max_size=8), st.booleans())


@given(
    fee=_values,
    status=st.sampled_from(["OK", "FAIL", None]),
    amount=_values,
    raw_amount=_values,
    name=st.sampled_from(["create", "create_v2", "buy", None]),
    program=st.sampled_from([PUMP_PROGRAM, "Other", None]),
    payer=st.sampled_from([TRADER, None, 7]),
)
@settings(max_examples=200, deadline=None)
def test_hypothesis_slim_never_changes_normalize(
    fee, status, amount, raw_amount, name, program, payer
) -> None:
    item = _fat_item()
    p = item["parsed"]
    p["fee"], p["transactionStatus"], p["feePayer"] = fee, status, payer
    p["nativeTransfers"][1]["amount"] = amount
    p["tokenTransfers"][0]["rawTokenAmount"] = raw_amount
    p["instructions"][0]["instructionName"] = name
    p["instructions"][0]["programId"] = program
    assert normalize_transaction(slim_item(item)) == normalize_transaction(copy.deepcopy(item))
