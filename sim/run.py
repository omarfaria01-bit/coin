"""Simulator entry point (P3). Usage: python -m sim.run --scenario <name> --seeds N."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from sim.scenarios import REGISTRY


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def run_scenario(name: str, seeds: int, out_dir: Path | None = None) -> dict:
    if name not in REGISTRY:
        raise SystemExit(f"unknown scenario {name!r}; choose from {sorted(REGISTRY)}")
    fn = REGISTRY[name]
    runs = [dict(fn(seed), seed=seed) for seed in range(seeds)]
    flags = [r["pass"] for r in runs]
    if all(f == "skipped" for f in flags):
        overall: bool | str = "skipped"
    else:
        overall = all(f is True for f in flags)
    payload = {
        "scenario": name,
        "seeds": seeds,
        "commit": _git_commit(),
        "pass": overall,
        "runs": runs,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        payload["out"] = str(path)
    return payload


def exit_code(payload: dict, *, strict: bool) -> int:
    """Non-strict: skipped counts as success. Strict: every seed must pass."""
    runs = payload.get("runs") or []
    if strict:
        if not runs:
            return 1
        return 0 if all(run.get("pass") is True for run in runs) else 1
    return 0 if payload["pass"] in (True, "skipped") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim.run")
    parser.add_argument("--scenario", required=False, choices=sorted(REGISTRY))
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--out", default="reports/sim/")
    parser.add_argument(
        "--e2e",
        action="store_true",
        help="run full-epoch §14 scenarios via sim.epoch_runner (requires engine.epoch)",
    )
    parser.add_argument(
        "--acceptance",
        action="store_true",
        help="run the v0.3.3 §14 rows (sim.acceptance_v033); exit 1 if any row fails",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any seed is skipped or failed, or if no run happened",
    )
    args = parser.parse_args(argv)
    if args.seeds <= 0:
        raise SystemExit("--seeds must be > 0")
    if args.acceptance:
        from sim.acceptance_v033 import render, run_rows

        rows = run_rows(args.seeds)
        report = (
            Path("reports/sim_v033_acceptance.md") if args.out == "reports/sim/" else Path(args.out)
        )
        report.parent.mkdir(parents=True, exist_ok=True)
        head = f"# COIN_MATH v0.3.3 §14 rows (#84 step 1)\n\nSeeds: {args.seeds} per row.\n\n"
        report.write_text(head + render(rows), encoding="utf-8")
        print(render(rows), end="")
        return 0 if all(r.passed == r.seeds for r in rows) else 1
    if args.e2e:
        from sim.epoch_runner import main as e2e_main

        e2e_out = Path("reports/sim_epoch_e2e.md") if args.out == "reports/sim/" else Path(args.out)
        return e2e_main(["--seeds", str(args.seeds), "--out", str(e2e_out)])
    if not args.scenario:
        raise SystemExit("need --scenario or --e2e")
    payload = run_scenario(args.scenario, args.seeds, Path(args.out))
    print(
        json.dumps(
            {
                "scenario": payload["scenario"],
                "seeds": payload["seeds"],
                "pass": payload["pass"],
                "commit": payload["commit"],
            },
            indent=2,
        )
    )
    return exit_code(payload, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
