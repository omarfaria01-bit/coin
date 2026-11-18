"""tools/payout_inputs.py against a fake RPC. No network, no keys (#314)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.payout_inputs import load_config, main

ROOT = Path(__file__).resolve().parents[1]
D0 = 1_763_424_000  # 2025-11-18T00:00:00Z
DAY0 = "2025-11-18"
A = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"  # on-curve holders
B = "2xNweLHLqrxmofjtE4fNAYbQhJwM2ykrSu9a8gnhnwtF"
SYS = "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"
TEAM = "HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrH"
BASKET = "BasketMint1111111111111111111111111111111111"


class FakeRpc:
    def __init__(self, holders: dict[str, int], wallet: int) -> None:
        self.holders, self.wallet = holders, wallet

    def __call__(self, method: str, params: object) -> object:
        if method == "getTokenAccounts":
            rows = [{"owner": w, "amount": str(a)} for w, a in self.holders.items()]
            return {"token_accounts": rows if params["page"] == 1 else []}  # type: ignore[index]
        if method == "getTokenAccountsByOwner":
            info = {"tokenAmount": {"amount": str(self.wallet)}}
            return {"value": [{"account": {"data": {"parsed": {"info": info}}}}]}
        raise AssertionError(method)


@pytest.fixture
def cfg(tmp_path):
    led = tmp_path / "fee-ledger.jsonl"
    led.write_text(json.dumps({"event": "bought", "mint": BASKET, "spent": "300", "out": "200"}))
    c = {
        "mint": "OurMint",
        "system_wallet": SYS,
        "excluded": {},
        "team_wallets": [TEAM],
        "fee_bot_ledger": str(led),
        "state_dir": str(tmp_path / "state"),
    }
    p = tmp_path / "inputs.json"
    p.write_text(json.dumps(c))
    return p


def ok(cfg, cmd, rpc, now, capsys):
    assert main([cmd, "--config", str(cfg)], rpc=rpc, now=now) == 0
    return json.loads(capsys.readouterr().out)


def test_day_min_balance_exclusions_and_formats(cfg, tmp_path, capsys):
    rpc = FakeRpc({A: 300, B: 100, SYS: 50, TEAM: 50}, wallet=10**9)
    for h in range(24):
        rpc.holders[A] = 30 if h == 7 else 300  # sold most of it for one hour
        ok(cfg, "snapshot", rpc, D0 + h * 3600 + 2400, capsys)
    out = ok(cfg, "export", rpc, D0 + 86400 + 600, capsys)
    assert out == {"day": DAY0, "dir": out["dir"], "holders": 2, "mints": 1}
    d = Path(out["dir"])
    snap = {w["address"]: w for w in json.loads((d / "snapshot.json").read_text())["wallets"]}
    assert snap[A]["balance"] == "30" and snap[B]["balance"] == "100"  # day minimum
    assert snap[A]["holding_seconds"] == 86400 + 600 - 2400
    bal = json.loads((d / "balances.json").read_text())
    assert bal == {
        "system_wallet": SYS,
        "mints": {BASKET: {"amount": "1000000000", "price_lamports": "3/2"}},
    }
    assert json.loads((d / "exclude.json").read_text()) == {SYS: "system", TEAM: "team"}


def test_refuses_short_day_and_unsent_previous_plan(cfg, tmp_path, capsys):
    rpc = FakeRpc({A: 1}, wallet=5)
    ok(cfg, "snapshot", rpc, D0 + 3600, capsys)
    with pytest.raises(RuntimeError, match="snapshots"):
        main(["export", "--config", str(cfg)], rpc=rpc, now=D0 + 86400 + 600)
    sd = tmp_path / "state"
    plan = {
        "transfers": [
            {"memo": "GTASP10:pay:2025-11-17:x:y"},
            {"memo": "GTASP10:pay:2025-11-17:z:y"},
        ]
    }
    (sd / "plan-2025-11-17.json").write_text(json.dumps(plan))
    sent = {"event": "transfer", "status": "sent", "memo": "GTASP10:pay:2025-11-17:x:y"}
    (sd / "ledger.jsonl").write_text(json.dumps(sent) + "\n")
    with pytest.raises(RuntimeError, match="1 unsent"):
        main(["export", "--config", str(cfg)], rpc=rpc, now=D0 + 86400 + 600)


def test_config_is_strict(cfg, monkeypatch):
    c = json.loads(cfg.read_text())
    for bad in ({**c, "x": 1}, {**c, "excluded": {A: "friend"}}):
        cfg.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            load_config(cfg)
    cfg.write_text(json.dumps(c))
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    assert main(["snapshot", "--config", str(cfg)]) == 2


@pytest.mark.skipif(
    not (ROOT / "tools/payout_plan.py").exists(), reason="planner (#315) not merged"
)
def test_planner_accepts_the_export(cfg, tmp_path, capsys):
    rpc = FakeRpc({A: 300, B: 100}, wallet=10**9)
    for h in range(24):
        ok(cfg, "snapshot", rpc, D0 + h * 3600 + 2400, capsys)
    d = Path(ok(cfg, "export", rpc, D0 + 86400 + 600, capsys)["dir"])
    plan = tmp_path / "plan.json"
    args = ["--snapshot", d / "snapshot.json", "--balances", d / "balances.json"]
    args += ["--exclude", d / "exclude.json", "--day", DAY0, "--out", plan]
    subprocess.run([sys.executable, ROOT / "tools/payout_plan.py", *map(str, args)], check=True)
    p = json.loads(plan.read_text())
    assert p["schema"] == 1 and p["day"] == DAY0 and p["system_wallet"] == SYS
    paid = {t["wallet"]: int(t["amount"]) for t in p["transfers"]}
    assert paid[A] == 3 * paid[B]  # equal loyalty, 3:1 balances
