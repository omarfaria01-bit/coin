"""tools/run_epoch.py: offline fixture -> run_epoch -> epochs/<n>/ (issue #51)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.epoch_files import read_epoch
from tools.run_epoch import InputError, load_fixture, main, run

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run_epoch_two.json"


def _fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: dict, params: Path | None = None) -> Path:
    path = tmp_path / "fx.json"
    data["params"] = str(params or FIXTURE.parent / data["params"])
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _conserved(rows: list[dict], inflows: list[int]) -> None:
    carry = 0
    for row, inflow in zip(rows, inflows, strict=True):
        assert row["pot_in"] + inflow + carry == row["pot_next"] + row["paid"] + row["carry_next"]
        carry = row["carry_next"]


def test_two_epochs_one_call_writes_both_and_state(tmp_path: Path) -> None:
    rows = run(FIXTURE, tmp_path)
    assert [r["epoch"] for r in rows] == [0, 1]
    _conserved(rows, [w["pot_inflow"] for w in _fx()["epochs"]])
    assert rows[1]["pot_in"] == rows[0]["pot_next"] > 0
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["epoch"] == 2 and state["pot"] == rows[1]["pot_next"]
    assert state["carry"] and sum(state["carry"].values()) == rows[1]["carry_next"]
    for n in (0, 1):
        result, nxt, _tree = read_epoch(tmp_path / str(n))
        assert result.epoch == n and nxt.epoch == n + 1
    assert (tmp_path / "1" / "state.json").read_bytes() == (tmp_path / "state.json").read_bytes()


def test_state_carries_across_invocations_and_matches_single_run(tmp_path: Path) -> None:
    split, whole = tmp_path / "split", tmp_path / "whole"
    assert [r["epoch"] for r in run(FIXTURE, split, max_epochs=1)] == [0]
    assert json.loads((split / "state.json").read_text(encoding="utf-8"))["epoch"] == 1
    assert [r["epoch"] for r in run(FIXTURE, split)] == [1]
    assert run(FIXTURE, split) == []  # nothing pending
    run(FIXTURE, whole)
    for name in ("0/result.json", "1/result.json", "1/payouts.csv", "state.json"):
        assert (split / name).read_bytes() == (whole / name).read_bytes()


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path / "e"), "--dry-run"]) == 0
    assert not (tmp_path / "e").exists()
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [r["epoch"] for r in lines] == [0, 1] and all(r["written"] is None for r in lines)


def test_rerun_is_idempotent_and_refuses_changed_artifacts(tmp_path: Path) -> None:
    run(FIXTURE, tmp_path, max_epochs=1)
    (tmp_path / "state.json").unlink()
    assert run(FIXTURE, tmp_path, max_epochs=1)[0]["epoch"] == 0  # identical bytes: no-op
    data = _fx()
    data["epochs"][0]["pot_inflow"] += 1
    (tmp_path / "state.json").unlink()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        run(_write(tmp_path, data), tmp_path, max_epochs=1)


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda d: d.update(surprise=1), "surprise: Extra inputs are not permitted"),
        (lambda d: d["events"][0].update(memo="x"), "events.0.memo: Extra inputs"),
        (lambda d: d["events"][0].update(amount=1.5), "events.0.amount"),
        (lambda d: d["events"][0].update(src=d["events"][0]["dst"]), "wrong src/dst presence"),
        (lambda d: d["epochs"][1].update(t0=1), "epochs[1].t0 must equal epochs[0].t1"),
        (lambda d: d["epochs"][0].update(epoch=3), "epochs[0].epoch must be 0"),
        (lambda d: d.pop("prices"), "prices: Field required"),
        (lambda d: d["events"].append(dict(d["events"][0])), "duplicate event"),
    ],
)
def test_bad_fixture_rejected_with_clear_error(tmp_path: Path, mutate, needle: str) -> None:
    data = _fx()
    mutate(data)
    with pytest.raises(InputError, match="validation error") as exc:
        load_fixture(_write(tmp_path, data))
    assert needle in str(exc.value)


def test_engine_rejection_and_bad_state_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _fx()
    data["epochs"][0]["t1"] = data["epochs"][1]["t0"] = 3600  # not epoch.hours long
    assert main([str(_write(tmp_path, data)), "--out", str(tmp_path / "e")]) == 2
    assert "epoch 0: t1-t0 must equal epoch.hours*3600" in capsys.readouterr().err
    state = tmp_path / "s.json"
    state.write_text('{"epoch": 0, "pot": -1}', encoding="utf-8")
    assert main([str(FIXTURE), "--out", str(tmp_path / "e"), "--state", str(state)]) == 2
    err = capsys.readouterr().err
    assert (
        "pot: Input should be greater than or equal to 0" in err and "carry: Field required" in err
    )


def test_bad_params_file_rejected(tmp_path: Path) -> None:
    params = tmp_path / "coin.json"
    params.write_text('{"epoch": {"hours": 24, "extra": 1}}', encoding="utf-8")
    with pytest.raises(InputError, match=r"epoch\.extra: Extra inputs"):
        load_fixture(_write(tmp_path, _fx(), params))


def test_merkle_rail_writes_tree_matching_claims_root(tmp_path: Path) -> None:
    coin = json.loads((FIXTURE.parent / _fx()["params"]).read_text(encoding="utf-8"))
    coin["rewards"]["push_max_eligible"] = 0
    params = tmp_path / "coin.json"
    params.write_text(json.dumps(coin), encoding="utf-8")
    rows = run(_write(tmp_path, _fx(), params), tmp_path / "e", max_epochs=1)
    assert rows[0]["rail"] == "merkle"
    result, _state, tree = read_epoch(tmp_path / "e" / "0")
    assert tree is not None and tree.root.hex() == result.claims["root"]


def test_conservation_check_catches_tampering(tmp_path: Path) -> None:
    from dataclasses import replace

    from engine.epoch import empty_state, run_epoch
    from tools.run_epoch import build_inputs, check_conservation

    fx, params = load_fixture(FIXTURE)
    prev = empty_state()
    res, nxt = run_epoch(build_inputs(fx, fx.epochs[0]), params, prev)
    check_conservation(prev, fx.epochs[0].pot_inflow, res, nxt)
    with pytest.raises(AssertionError, match="conservation failed"):
        check_conservation(prev, fx.epochs[0].pot_inflow, res, replace(nxt, pot=nxt.pot + 1))
