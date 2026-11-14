"""Golden v0.3.3 epoch replay + determinism (#83).

Regenerate (the only way): uv run python tools/regen_golden.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.config_loader import load_coin
from engine.params import CoinParams
from tools.regen_golden import FIXTURE, GOLDEN, ROOT, digest, render

REGEN = "uv run python tools/regen_golden.py"


def _golden() -> dict[str, bytes]:
    return {
        p.relative_to(GOLDEN).as_posix(): p.read_bytes()
        for p in sorted(GOLDEN.rglob("*"))
        if p.is_file()
    }


def test_replay_is_byte_identical_to_goldens(tmp_path: Path) -> None:
    fresh = render(tmp_path)
    golden = _golden()
    assert sorted(fresh) == sorted(golden), f"file set changed; run `{REGEN}`"
    for name, blob in golden.items():
        assert fresh[name] == blob, f"{name} differs from the golden; run `{REGEN}` and review"


def test_goldens_use_the_committed_defaults() -> None:
    """Changing any default changes the params dumped into inputs_hash → the goldens fail."""
    params_path = (FIXTURE.parent / json.loads(FIXTURE.read_text())["params"]).resolve()
    assert load_coin(params_path) == CoinParams()


@pytest.mark.parametrize("seed", ["0", "1", "424242"])
def test_replay_independent_of_hash_seed(tmp_path: Path, seed: str) -> None:
    code = (
        "import sys, pathlib; sys.path.insert(0, sys.argv[1]);"
        "from tools.regen_golden import digest, render;"
        "print(digest(render(pathlib.Path(sys.argv[2]))))"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), str(tmp_path)],
        env=env, capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert out.stdout.strip() == digest(_golden())


def test_golden_covers_the_v033_paths() -> None:
    """The fixture exercises what #83 asks for, so a silent fixture change can't hollow it out."""
    states = [json.loads((GOLDEN / str(n) / "state.json").read_text()) for n in range(3)]
    results = [json.loads((GOLDEN / str(n) / "result.json").read_text()) for n in range(3)]
    assert states[0]["forfeit_until"], "soft-vesting forfeit"
    assert any(v == 0.5 for v in states[0]["unlocked"].values()), "price unlock from reserves"
    assert states[0]["carry"] and not states[1]["carry"], "pending carried, then paid"
    assert any(s["score"] == 0 and s["cluster"] not in states[0]["forfeit_until"]
               for s in results[1]["scores"]), "sniper below T_START scores 0"  # fmt: skip
    clusters = {s["cluster"] for s in results[0]["scores"]}
    assert len(clusters) == 4, "S2-funded wallet merged into its funder's cluster"
    book = json.loads((GOLDEN / "2" / "balances.json").read_text())
    assert sum(b["paid_total"] for b in book.values()) == sum(
        sum(r["transferred_or_claimable"].values()) for r in results
    )
