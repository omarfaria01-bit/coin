#!/usr/bin/env python3
"""Offline epoch runner: JSON fixture -> engine.epoch.run_epoch -> epochs/<n>/ (§8).

Runs every fixture window after the carried `state.json` (schema: `Fixture`, unknown keys
rejected), writes artifacts via adapters.epoch_files, updates `state.json`. No network/clock.

    uv run python tools/run_epoch.py tests/fixtures/run_epoch_two.json --out epochs
    uv run python tools/run_epoch.py FIXTURE --out epochs --dry-run   # summary only
"""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import base58  # noqa: E402

from adapters.config_loader import load_coin  # noqa: E402
from adapters.epoch_files import write_epoch  # noqa: E402
from engine.epoch import EpochInputs, EpochResult, EpochState, VestingEntry, run_epoch  # noqa: E402
from engine.merkle import MerkleTree, build, leaf  # noqa: E402
from engine.params import CoinParams  # noqa: E402
from engine.prices import ReservePoint  # noqa: E402
from engine.types import EventKind, FirstFunding, PricePoint, SolTransfer, TokenEvent  # noqa: E402


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EventIn(_Strict):
    slot: int = Field(ge=0)
    ts: int
    sig: str = Field(min_length=1)
    ix: int = Field(ge=0)
    kind: Literal["buy", "sell", "transfer"]
    src: str | None = None
    dst: str | None = None
    amount: int = Field(gt=0)
    lamports: int | None = Field(default=None, ge=0)
    fee_payer: str = Field(min_length=1)

    @model_validator(mode="after")
    def _sides(self) -> EventIn:
        want_src, want_dst = {"buy": (False, True), "sell": (True, False)}.get(
            self.kind, (True, True)
        )
        if (self.src is not None) != want_src or (self.dst is not None) != want_dst:
            raise ValueError(f"{self.kind} event {self.sig}:{self.ix} has wrong src/dst presence")
        if (self.lamports is None) != (self.kind == "transfer"):
            raise ValueError(f"{self.kind} event {self.sig}:{self.ix}: lamports only for buy/sell")
        return self


class SolTransferIn(_Strict):
    slot: int = Field(ge=0)
    ts: int
    sig: str = Field(min_length=1)
    src: str
    dst: str
    lamports: int = Field(gt=0)


class FundingIn(_Strict):
    wallet: str
    funder: str
    ts: int
    created_ts: int


class PriceIn(_Strict):
    ts: int
    price: float = Field(gt=0, allow_inf_nan=False)


class VestingIn(_Strict):
    wallet: str
    vested_amount: int = Field(ge=0)
    p_entry: str | int | float = Field(
        description="Q base units per token base unit: 'num/den' string (exact), int or float"
    )
    t0: int

    @field_validator("p_entry")
    @classmethod
    def _positive_rational(cls, v: str | int | float) -> str | int | float:
        try:
            ok = Fraction(str(v)) > 0
        except (ValueError, ZeroDivisionError):
            ok = False
        if not ok:
            raise ValueError("p_entry must be a positive rational")
        return v


class ReserveIn(_Strict):
    ts: int
    reserve_quote: int = Field(gt=0)
    reserve_base: int = Field(gt=0)


class WindowIn(_Strict):
    epoch: int = Field(ge=0)
    t0: int
    t1: int
    slot_range: tuple[int, int]
    pot_inflow: int = Field(ge=0)

    @model_validator(mode="after")
    def _order(self) -> WindowIn:
        if self.t1 <= self.t0 or self.slot_range[1] < self.slot_range[0]:
            raise ValueError(f"epoch {self.epoch}: need t0 < t1 and slot_range ascending")
        return self


class Fixture(_Strict):
    """History is shared; each window sees only rows with ts < t1."""

    params: str = Field(description="Path to coin.json, relative to the fixture file")
    decimals: int = Field(ge=0, le=18)
    total_supply: int = Field(gt=0, description="Token base units (v0.3.3 §2)")
    sol_usd: float = Field(gt=0, allow_inf_nan=False)
    excluded: list[str] = []
    hubs: list[str] = []
    vesting: list[VestingIn] = Field([], description="Seeds epoch 0 only (no state.json yet)")
    events: list[EventIn]
    sol_transfers: list[SolTransferIn] = []
    fundings: list[FundingIn] = []
    prices: list[PriceIn] = Field(min_length=1)
    reserves: list[ReserveIn] = Field([], description="§0 pool reserves for the §11 unlock")
    epochs: list[WindowIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _windows(self) -> Fixture:
        for i, w in enumerate(self.epochs):
            if w.epoch != i:
                raise ValueError(f"epochs[{i}].epoch must be {i}, got {w.epoch}")
            if i and w.t0 != self.epochs[i - 1].t1:
                raise ValueError(f"epochs[{i}].t0 must equal epochs[{i - 1}].t1")
        keys = [(e.slot, e.sig, e.ix) for e in self.events]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate event (slot, sig, ix)")
        return self


class StateIn(_Strict):
    """Mirror of the state.json written by adapters.epoch_files."""

    epoch: int = Field(ge=0)
    pot: int = Field(ge=0)
    carry: dict[str, int]
    forfeit_until: dict[str, int]
    unlocked: dict[str, float]
    vesting: list[VestingIn]
    paid_total: dict[str, int] = {}


class InputError(ValueError):
    """Bad fixture or state; message is shown to the user as-is."""


def _validation_msg(where: Path, exc: ValidationError) -> str:
    lines = [f"{where}: {exc.error_count()} validation error(s)"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def load_fixture(path: Path) -> tuple[Fixture, CoinParams]:
    try:
        fx = Fixture.model_validate_json(Path(path).read_bytes())
    except ValidationError as exc:
        raise InputError(_validation_msg(path, exc)) from None
    params_path = (Path(path).parent / fx.params).resolve()
    try:
        params = load_coin(params_path)
    except ValidationError as exc:
        raise InputError(_validation_msg(params_path, exc)) from None
    return fx, params


def load_state(path: Path, fx: Fixture) -> EpochState:
    if not path.exists():
        return EpochState(
            0, 0, {}, {}, {}, tuple(VestingEntry(**v.model_dump()) for v in fx.vesting)
        )
    try:
        st = StateIn.model_validate_json(path.read_bytes())
    except ValidationError as exc:
        raise InputError(_validation_msg(path, exc)) from None
    vest = tuple(VestingEntry(**v.model_dump()) for v in st.vesting)
    return EpochState(**{**st.model_dump(), "vesting": vest})


def build_inputs(fx: Fixture, w: WindowIn) -> EpochInputs:
    return EpochInputs(
        t0=w.t0,
        t1=w.t1,
        slot_range=w.slot_range,
        events=tuple(
            TokenEvent(**{**e.model_dump(), "kind": EventKind(e.kind)})
            for e in fx.events
            if e.ts < w.t1
        ),
        sol_transfers=tuple(SolTransfer(**s.model_dump()) for s in fx.sol_transfers if s.ts < w.t1),
        fundings=tuple(FirstFunding(**f.model_dump()) for f in fx.fundings if f.ts < w.t1),
        prices=tuple(PricePoint(p.ts, p.price) for p in fx.prices if p.ts < w.t1),
        decimals=fx.decimals,
        sol_usd=fx.sol_usd,
        pot_inflow=w.pot_inflow,
        excluded=frozenset(fx.excluded),
        hubs=frozenset(fx.hubs),
        total_supply=fx.total_supply,
        reserves=tuple(ReservePoint(**r.model_dump()) for r in fx.reserves if r.ts < w.t1),
    )


def check_conservation(prev: EpochState, inflow: int, res: EpochResult, nxt: EpochState) -> None:
    """ENGINE_DESIGN §8 invariant, re-checked outside the engine before anything is written."""
    lhs = prev.pot + inflow + sum(prev.carry.values())
    rhs = nxt.pot + sum(res.transferred_or_claimable.values()) + sum(nxt.carry.values())
    if lhs != rhs or res.pot != nxt.pot:
        raise AssertionError(f"epoch {res.epoch}: conservation failed {lhs} != {rhs}")


def claims_tree(res: EpochResult) -> MerkleTree | None:
    """Rebuild the tree behind result.claims (same leaves as merkle.claims_document)."""
    if res.claims is None:
        return None
    rows = res.claims["claims"]
    tree = build([leaf(base58.b58decode(c["claimant"]), c["amount_unlocked"], 0) for c in rows])
    if tree.root.hex() != res.claims["root"]:
        raise AssertionError(f"epoch {res.epoch}: rebuilt merkle root mismatch")
    return tree


def summary(
    prev: EpochState, inflow: int, res: EpochResult, nxt: EpochState, dest: Path | None
) -> dict:
    return {
        "epoch": res.epoch,
        "rail": res.rail,
        "pot_prev": prev.pot,
        "pot_inflow": inflow,
        "pot_next": nxt.pot,
        "paid": sum(res.transferred_or_claimable.values()),
        "carry_next": sum(nxt.carry.values()),
        "paid_total": sum(nxt.paid_total.values()),
        "wallets_paid": len(res.transferred_or_claimable),
        "inputs_hash": res.inputs_hash,
        "written": str(dest) if dest else None,
    }


def run(
    fixture: Path,
    out: Path,
    state_path: Path | None = None,
    *,
    dry_run: bool = False,
    max_epochs: int | None = None,
) -> list[dict]:
    fx, params = load_fixture(fixture)
    state_path = state_path or out / "state.json"
    state = load_state(state_path, fx)
    if state.epoch > len(fx.epochs):
        raise InputError(f"{state_path}: epoch {state.epoch} is past the fixture's last window")
    pending = fx.epochs[state.epoch :][:max_epochs]
    rows: list[dict] = []
    for w in pending:
        try:
            res, nxt = run_epoch(build_inputs(fx, w), params, state)
        except ValueError as exc:
            raise InputError(f"epoch {w.epoch}: {exc}") from None
        check_conservation(state, w.pot_inflow, res, nxt)
        dest = None
        if not dry_run:
            dest = write_epoch(out, res, nxt, claims_tree(res))
            tmp = state_path.parent / (state_path.name + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes((dest / "state.json").read_bytes())
            tmp.replace(state_path)
        rows.append(summary(state, w.pot_inflow, res, nxt, dest))
        state = nxt
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("fixture", type=Path, help="Epoch input JSON (see Fixture schema)")
    p.add_argument("--out", type=Path, default=ROOT / "epochs", help="Artifacts root")
    p.add_argument("--state", type=Path, help="Carried state (default: <out>/state.json)")
    p.add_argument("--epochs", type=int, help="Run at most N pending epochs (default: all)")
    p.add_argument("--dry-run", action="store_true", help="Print summary only, write nothing")
    args = p.parse_args(argv)
    if args.epochs is not None and args.epochs < 1:
        p.error("--epochs must be >= 1")
    try:
        rows = run(args.fixture, args.out, args.state, dry_run=args.dry_run, max_epochs=args.epochs)
    except (InputError, FileNotFoundError, FileExistsError, AssertionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for row in rows:
        print(json.dumps(row, sort_keys=True))
    if not rows:
        print("nothing to do: every fixture epoch is already in state", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
