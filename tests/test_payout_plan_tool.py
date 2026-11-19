"""Payout planner (D46, #315): conservation, dust carry, exclusions, determinism, carry-in."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.rewards import TOKEN_ACCOUNT_RENT_LAMPORTS as RENT
from tools.payout_plan import build_plan, dumps, main, memo_key

SYS = "SyS1111111111111111111111111111111111111111"
M1, M2 = (
    "MintA111111111111111111111111111111111111111",
    "MintB11111111111111111111111111111111111111",
)
DAY = "2026-11-19"
H4 = 4 * 3600


def bal(amounts: dict[str, int], price: str = str(RENT)) -> dict:
    return {
        "system_wallet": SYS,
        "mints": {m: {"amount": str(a), "price_lamports": price} for m, a in amounts.items()},
    }


def snap(*rows: tuple[str, int, int]) -> dict:
    return {"wallets": [{"address": a, "balance": b, "holding_seconds": h} for a, b, h in rows]}


def check_conservation(plan: dict) -> None:
    for mint, t in plan["totals"].items():
        paid = sum(int(x["amount"]) for x in plan["transfers"] if x["mint"] == mint)
        car = sum(int(x["amount"]) for x in plan["carried"] if x["mint"] == mint)
        assert paid == int(t["paid"]) and car == int(t["carried"])
        assert paid + car == int(t["accrued"])


def test_pro_rata_by_loyalty_weight_and_memo() -> None:
    plan = build_plan(
        day=DAY, snapshot=snap(("a", 100, H4), ("b", 100, 3600)), balances=bal({M1: 600})
    )
    got = {t["wallet"]: int(t["amount"]) for t in plan["transfers"]}
    assert got == {"a": 500, "b": 100}  # 5x vs 1x
    assert plan["transfers"][0]["memo"] == memo_key(DAY, "a", M1) == f"GTASP10:pay:{DAY}:a:{M1}"
    assert plan["carried"] == [] and plan["schema"] == 1 and plan["system_wallet"] == SYS
    check_conservation(plan)


def test_dust_is_carried_not_paid() -> None:
    # price 1 lamport/unit: 'a' gets 2M (worth >= rent, paid), 'b' gets 400k (< rent, carried)
    plan = build_plan(
        day=DAY,
        snapshot=snap(("a", 5, H4), ("b", 1, H4)),
        balances=bal({M1: 2_400_000}, price="1"),
    )
    assert [(t["wallet"], t["amount"]) for t in plan["transfers"]] == [("a", "2000000")]
    assert plan["carried"] == [{"wallet": "b", "mint": M1, "amount": "400000"}]
    check_conservation(plan)


def test_carry_in_is_added_and_paid_once_over_floor() -> None:
    carry = [{"wallet": "b", "mint": M1, "amount": "1200000"}]
    plan = build_plan(
        day=DAY,
        snapshot=snap(("a", 5, H4), ("b", 1, H4)),
        balances=bal({M1: 1_200_000 + 2_400_000}, price="1"),
        carry_in=carry,
    )
    got = {t["wallet"]: int(t["amount"]) for t in plan["transfers"]}
    assert got == {"a": 2_000_000, "b": 1_600_000}  # 1.2M old carry + 400k new credit
    assert plan["carried"] == []
    check_conservation(plan)


def test_carry_in_from_previous_plan_and_absent_wallet_keeps_carry() -> None:
    prev = {"carried": [{"wallet": "gone", "mint": M1, "amount": "7"}]}
    plan = build_plan(
        day=DAY, snapshot=snap(("a", 1, H4)), balances=bal({M1: 107}, price="1"), carry_in=prev
    )
    assert {"wallet": "gone", "mint": M1, "amount": "7"} in plan["carried"]
    assert {"wallet": "a", "mint": M1, "amount": "100"} in plan["carried"]  # dust at 1 lamport
    check_conservation(plan)


def test_exclusions_earn_nothing_and_their_carry_is_resplit() -> None:
    dev_snap = snap(("a", 1, H4), ("pool", 10**9, H4), ("dev", 10**9, H4))
    dev_snap["wallets"][2]["excluded_reason"] = "team"
    plan = build_plan(
        day=DAY,
        snapshot=dev_snap,
        balances=bal({M1: 1000}),
        exclude={"pool": "pool", "burn1": "burn"},
        carry_in=[{"wallet": "dev", "mint": M1, "amount": "300"}],
    )
    assert plan["transfers"] == [
        {"wallet": "a", "mint": M1, "amount": "1000", "memo": memo_key(DAY, "a", M1)}
    ]
    assert plan["excluded"] == [
        {"wallet": SYS, "reason": "system"},
        {"wallet": "burn1", "reason": "burn"},
        {"wallet": "dev", "reason": "team"},
        {"wallet": "pool", "reason": "pool"},
    ]
    check_conservation(plan)


def test_nobody_eligible_carries_on_system_wallet() -> None:
    plan = build_plan(day=DAY, snapshot=snap(("a", 100, 60)), balances=bal({M1: 50}))
    assert plan["transfers"] == []
    assert plan["carried"] == [{"wallet": SYS, "mint": M1, "amount": "50"}]
    check_conservation(plan)


@pytest.mark.parametrize(
    ("kwargs", "msg"),
    [
        ({"exclude": {"x": "friend"}}, "reason"),
        ({"carry_in": [{"wallet": "a", "mint": M1, "amount": "999"}]}, "carry-in"),
        ({"carry_in": [{"wallet": "a", "mint": M2, "amount": "1"}]}, "no balance"),
        ({"balances": bal({M1: "1.5"})}, "amount"),
        ({"balances": bal({M1: 5}, 0.5)}, "price"),
        ({"snapshot": snap(("a", 1, H4), ("a", 2, H4))}, "duplicate"),
    ],
)
def test_bad_inputs_are_rejected(kwargs: dict, msg: str) -> None:
    args = {"day": DAY, "snapshot": snap(("a", 1, H4)), "balances": bal({M1: 10})} | kwargs
    with pytest.raises(ValueError, match=msg):
        build_plan(**args)


holders = st.dictionaries(
    st.text("abcdefgh", min_size=1, max_size=3),
    st.tuples(st.integers(0, 10**12), st.integers(0, 40 * 86_400)),
    max_size=12,
)


@settings(max_examples=150, deadline=None)
@given(
    rows=holders,
    amounts=st.dictionaries(st.sampled_from([M1, M2]), st.integers(0, 10**15), min_size=1),
    carry=st.lists(
        st.tuples(st.text("abcz", min_size=1, max_size=2), st.integers(0, 10**6)), max_size=6
    ),
    price=st.sampled_from(["0", "1", "1/1000", str(RENT)]),
)
def test_conservation_and_determinism(rows, amounts, carry, price) -> None:
    mint = sorted(amounts)[0]
    carry_rows = [{"wallet": w, "mint": mint, "amount": str(a)} for w, a in carry]
    amounts[mint] += sum(a for _, a in carry)  # carry-in always sits in the balance
    kw = {
        "day": DAY,
        "snapshot": snap(*((w, b, h) for w, (b, h) in rows.items())),
        "balances": bal(amounts, price),
        "exclude": {"z": "cex"},
        "carry_in": carry_rows,
    }
    plan = build_plan(**kw)
    check_conservation(plan)
    for mint_, t in plan["totals"].items():
        assert int(t["accrued"]) == amounts[mint_]
    assert all(t["wallet"] not in ("z", SYS) for t in plan["transfers"])
    assert dumps(build_plan(**kw)) == dumps(plan)
    keys = [t["memo"] for t in plan["transfers"]]
    assert len(keys) == len(set(keys))


def test_cli_writes_identical_bytes(tmp_path: Path) -> None:
    files = {
        "snap": snap(("a", 3, H4), ("b", 1, 2 * 3600)),
        "bal": bal({M1: 9_000_000, M2: 5}),
        "excl": [{"wallet": "c", "reason": "cex"}],
        "carry": {"carried": []},
    }
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data))
    outs = []
    for i in range(2):
        out = tmp_path / f"plan{i}.json"
        args = [
            "--snapshot",
            "snap",
            "--balances",
            "bal",
            "--exclude",
            "excl",
            "--carry-in",
            "carry",
        ]
        argv = [x if x.startswith("--") else str(tmp_path / f"{x}.json") for x in args]
        assert main([*argv, "--day", DAY, "--out", str(out)]) == 0
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    plan = json.loads(outs[0])
    check_conservation(plan)
    assert list(plan) == [
        "schema",
        "day",
        "system_wallet",
        "transfers",
        "carried",
        "excluded",
        "totals",
    ]


def test_d47_weight_field_overrides_holding_seconds() -> None:
    """Export rows carry `weight` (balance-hours x loyalty): the plan splits by it exactly."""
    snapshot = {
        "wallets": [
            {"address": "A", "balance": 1, "weight": "3/1", "holding_seconds": 0},
            {"address": "B", "balance": 1000, "weight": "1/1"},
        ]
    }
    plan = build_plan(day=DAY, snapshot=snapshot, balances=bal({M1: 4_000_000}))
    paid = {t["wallet"]: int(t["amount"]) for t in plan["transfers"]}
    assert paid == {"A": 3_000_000, "B": 1_000_000}
    check_conservation(plan)
