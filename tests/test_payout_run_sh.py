"""ops/payout-bot/run.sh step order and idempotency, with stub steps (#314). No network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-11-19"

PLANNER = """import json, sys
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
open(a["--out"], "w").write(json.dumps({"day": a["--day"], "carry": a.get("--carry-in")}))
open(sys.argv[0] + ".calls", "a").write("plan\\n")
"""


def setup(tmp: Path) -> tuple[Path, dict]:
    repo, sd, cfg = tmp / "repo", tmp / "state", tmp / "cfg"
    for d in (repo / "tools", repo / "ops/payout-bot", sd, cfg):
        d.mkdir(parents=True)
    (cfg / "inputs.json").write_text(json.dumps({"state_dir": str(sd)}))
    (repo / "tools/payout_inputs.py").write_text(f'print(\'{{"day": "{DAY}"}}\')\n')
    (repo / "tools/payout_plan.py").write_text(PLANNER)
    node = tmp / "node"
    node.write_text(f'#!/bin/sh\necho "$3" >> {tmp}/sends\n')
    node.chmod(0o755)
    env = os.environ | {
        "COIN_REPO": str(repo),
        "PAYOUT_CFG_DIR": str(cfg),
        "COIN_PY": sys.executable,
        "COIN_NODE": str(node),
    }
    return sd, env


def run(env: dict) -> None:
    subprocess.run(["bash", str(ROOT / "ops/payout-bot/run.sh")], env=env, check=True)


def test_first_day_then_rerun_and_carry(tmp_path):
    sd, env = setup(tmp_path)
    run(env)
    plan = sd / f"plan-{DAY}.json"
    assert json.loads(plan.read_text()) == {"day": DAY, "carry": None}
    assert (tmp_path / "sends").read_text().split() == [str(plan)]
    run(env)  # same day again: no new plan, sends re-run (the sender skips sent memos)
    calls = (tmp_path / "repo/tools/payout_plan.py.calls").read_text().split()
    assert calls == ["plan"]
    assert (tmp_path / "sends").read_text().split() == [str(plan)] * 3


def test_previous_plan_sent_first_and_used_as_carry(tmp_path):
    sd, env = setup(tmp_path)
    prev = sd / "plan-2026-11-18.json"
    prev.write_text("{}")
    run(env)
    plan = sd / f"plan-{DAY}.json"
    assert json.loads(plan.read_text())["carry"] == str(prev)
    assert (tmp_path / "sends").read_text().split() == [str(prev), str(plan)]
