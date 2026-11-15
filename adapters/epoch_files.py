"""Deterministic epoch artifact writer (ENGINE_DESIGN §8). Offline only."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from adapters.ingest import load_balances
from engine.balances import WalletBalance
from engine.merkle import MerkleTree
from engine.types import ClusterId, WalletId

_FILES = (
    "result.json",
    "payouts.csv",
    "tree.json",
    "state.json",
    "balances.json",
    "inputs_hash.txt",
)


def _types():
    try:
        from engine.epoch import ClusterScore, EpochResult, EpochState, VestingEntry

        return ClusterScore, EpochResult, EpochState, VestingEntry
    except ImportError:
        return _ClusterScore, _EpochResult, _EpochState, _VestingEntry


@dataclass(frozen=True, slots=True)
class _VestingEntry:
    wallet: WalletId
    vested_amount: int
    p_entry: Fraction
    t0: int


@dataclass(frozen=True, slots=True)
class _EpochState:
    epoch: int
    pot: int
    carry: Mapping[WalletId, int]
    forfeit_until: Mapping[ClusterId, int]
    unlocked: Mapping[WalletId, float]
    vesting: tuple[_VestingEntry, ...]
    paid_total: Mapping[WalletId, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _ClusterScore:
    cluster: ClusterId
    twab: float
    hold: float
    churn: float
    boost: float
    score: float
    share: float


@dataclass(frozen=True, slots=True)
class _EpochResult:
    epoch: int
    payouts: Mapping[WalletId, int]
    scores: tuple[_ClusterScore, ...]
    rollover: int
    dust: int
    pot: int
    rail: Literal["push", "merkle", "none"]
    claims: dict[str, Any] | None
    push: tuple[tuple[WalletId, int], ...]
    review: tuple[ClusterId, ...]
    inputs_hash: str
    transferred_or_claimable: Mapping[WalletId, int]


def _require_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int (no floats for money), got {type(value).__name__}")
    return value


def _sorted_int_map(name: str, mapping: Mapping[Any, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in sorted(mapping.items(), key=lambda kv: str(kv[0])):
        out[str(key)] = _require_int(f"{name}[{key}]", value)
    return out


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Fraction):
        return str(value)  # exact "num/den" (or "n")
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + chr(10)


def _payouts_csv(payouts: Mapping[str, int]) -> str:
    lines = ["wallet,amount"]
    for wallet, amount in sorted(payouts.items(), key=lambda kv: kv[0]):
        lines.append(f"{wallet},{_require_int('payouts[' + wallet + ']', amount)}")
    return chr(10).join(lines) + chr(10)


def _tree_payload(tree: MerkleTree | None) -> dict[str, Any]:
    if tree is None:
        return {"root": None, "layers": []}
    return {
        "root": tree.root.hex(),
        "layers": [[node.hex() for node in layer] for layer in tree._layers],
    }


def _result_payload(result: Any) -> dict[str, Any]:
    data = _jsonable(result)
    data["epoch"] = _require_int("epoch", data["epoch"])
    data["pot"] = _require_int("pot", data["pot"])
    data["rollover"] = _require_int("rollover", data["rollover"])
    data["dust"] = _require_int("dust", data["dust"])
    data["payouts"] = _sorted_int_map("payouts", data["payouts"])
    transferred = data.get("transferred_or_claimable") or {}
    data["transferred_or_claimable"] = _sorted_int_map("transferred_or_claimable", transferred)
    scores = data.get("scores") or []
    data["scores"] = sorted(scores, key=lambda row: str(row["cluster"]))
    push = data.get("push") or []
    # push rows are [wallet, amount] after jsonable(tuple)
    norm_push = []
    for row in push:
        wallet, amount = row[0], row[1]
        norm_push.append([wallet, _require_int(f"push[{wallet}]", amount)])
    data["push"] = sorted(norm_push, key=lambda row: row[0])
    data["review"] = sorted(str(c) for c in (data.get("review") or []))
    return data


def _state_payload(state: Any) -> dict[str, Any]:
    data = _jsonable(state)
    data["epoch"] = _require_int("state.epoch", data["epoch"])
    data["pot"] = _require_int("state.pot", data["pot"])
    data["carry"] = _sorted_int_map("carry", data.get("carry") or {})
    data["paid_total"] = _sorted_int_map("paid_total", data.get("paid_total") or {})
    data["forfeit_until"] = _sorted_int_map("forfeit_until", data.get("forfeit_until") or {})
    unlocked = data.get("unlocked") or {}
    data["unlocked"] = {
        str(k): float(v) for k, v in sorted(unlocked.items(), key=lambda kv: str(kv[0]))
    }
    vesting = data.get("vesting") or []
    for row in vesting:
        row["vested_amount"] = _require_int("vested_amount", row["vested_amount"])
        row["t0"] = _require_int("t0", row["t0"])
    data["vesting"] = sorted(vesting, key=lambda row: str(row["wallet"]))
    return data


def _balances_payload(state_d: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """COIN_MATH §13 running balance per wallet, in Q base units."""
    pending, paid = state_d["carry"], state_d["paid_total"]
    out: dict[str, dict[str, int]] = {}
    for wallet in sorted(set(pending) | set(paid)):
        p, q = pending.get(wallet, 0), paid.get(wallet, 0)
        out[wallet] = {"earned_total": p + q, "paid_total": q, "pending": p}
    return out


def _contents(
    result: Any,
    state: Any,
    tree: MerkleTree | None,
    push_plan: Any | None = None,
) -> dict[str, bytes]:
    result_d = _result_payload(result)
    state_d = _state_payload(state)
    files = {
        "result.json": _canonical(result_d),
        "payouts.csv": _payouts_csv(result_d["payouts"]),
        "tree.json": _canonical(_tree_payload(tree)),
        "state.json": _canonical(state_d),
        "balances.json": _canonical(_balances_payload(state_d)),
        "inputs_hash.txt": str(result_d["inputs_hash"]) + chr(10),
    }
    if push_plan is not None:
        files["push.json"] = _canonical(_jsonable(push_plan))
    return {name: text.encode("utf-8") for name, text in files.items()}


def write_epoch(
    dir: Path,
    result: Any,
    state: Any,
    tree: MerkleTree | None,
    push_plan: Any | None = None,
) -> Path:
    """Write `dir/<result.epoch>/{result,payouts,tree,state,balances,inputs_hash}`.

    Refuses to overwrite an existing epoch directory whose bytes would change.
    A second write of identical content is a no-op.
    """
    base = Path(dir)
    result_d = _result_payload(result)
    dest = base / str(result_d["epoch"])
    encoded = _contents(result, state, tree, push_plan=push_plan)
    if dest.exists():
        if not dest.is_dir():
            raise FileExistsError(f"refusing to overwrite {dest} (not a directory)")
        current: dict[str, bytes] = {}
        files_to_check = list(_FILES)
        if (dest / "push.json").is_file() or "push.json" in encoded:
            files_to_check.append("push.json")
        for name in files_to_check:
            path = dest / name
            if path.is_file():
                current[name] = path.read_bytes()
        if current == encoded:
            return dest
        raise FileExistsError(f"refusing to overwrite {dest} with different content")
    dest.mkdir(parents=True)
    for name, blob in encoded.items():
        (dest / name).write_bytes(blob)
    return dest


def _load_tree(data: Mapping[str, Any]) -> MerkleTree | None:
    root = data.get("root")
    layers = data.get("layers") or []
    if root is None:
        return None
    return MerkleTree(
        root=bytes.fromhex(root),
        _layers=tuple(tuple(bytes.fromhex(node) for node in layer) for layer in layers),
    )


def _build_result(data: dict[str, Any]):
    ClusterScore, EpochResult, _EpochState, _Vesting = _types()
    scores = tuple(
        ClusterScore(
            cluster=row["cluster"],
            twab=row["twab"],
            hold=row["hold"],
            churn=row["churn"],
            boost=row["boost"],
            score=row["score"],
            share=row["share"],
        )
        for row in data.get("scores") or []
    )
    push = tuple((row[0], int(row[1])) for row in (data.get("push") or []))
    return EpochResult(
        epoch=int(data["epoch"]),
        payouts=dict(data["payouts"]),
        scores=scores,
        rollover=int(data["rollover"]),
        dust=int(data["dust"]),
        pot=int(data["pot"]),
        rail=data["rail"],
        claims=data.get("claims"),
        push=push,
        review=tuple(data.get("review") or ()),
        inputs_hash=data["inputs_hash"],
        transferred_or_claimable=dict(data.get("transferred_or_claimable") or {}),
    )


def _build_state(data: dict[str, Any]):
    _Score, _Result, EpochState, VestingEntry = _types()
    vesting = tuple(
        VestingEntry(
            wallet=row["wallet"],
            vested_amount=int(row["vested_amount"]),
            p_entry=Fraction(str(row["p_entry"])),
            t0=int(row["t0"]),
        )
        for row in data.get("vesting") or []
    )
    return EpochState(
        epoch=int(data["epoch"]),
        pot=int(data["pot"]),
        carry=dict(data.get("carry") or {}),
        forfeit_until=dict(data.get("forfeit_until") or {}),
        unlocked={k: float(v) for k, v in (data.get("unlocked") or {}).items()},
        vesting=vesting,
        paid_total=dict(data.get("paid_total") or {}),
    )


def read_balances(dir: Path) -> dict[WalletId, WalletBalance]:
    """Load `dir/balances.json` back into the §13 running book, validated first."""
    path = Path(dir) / "balances.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path}: missing balances.json")
    return {
        wallet: WalletBalance(
            wallet=wallet, earned_total=row.earned_total, paid_total=row.paid_total
        )
        for wallet, row in load_balances(path).items()
    }


def read_epoch(dir: Path) -> tuple[Any, Any, MerkleTree | None]:
    """Load `dir` (an `epochs/<n>/` folder) back into result, state, tree."""
    dest = Path(dir)
    missing = [name for name in _FILES if not (dest / name).is_file()]
    if missing:
        raise FileNotFoundError(f"incomplete epoch dir {dest}: missing {missing}")
    result_d = json.loads((dest / "result.json").read_text(encoding="utf-8"))
    state_d = json.loads((dest / "state.json").read_text(encoding="utf-8"))
    tree_d = json.loads((dest / "tree.json").read_text(encoding="utf-8"))
    hash_txt = (dest / "inputs_hash.txt").read_text(encoding="utf-8")
    if hash_txt.strip() != str(result_d.get("inputs_hash")):
        raise ValueError("inputs_hash.txt does not match result.json")
    return _build_result(result_d), _build_state(state_d), _load_tree(tree_d)
