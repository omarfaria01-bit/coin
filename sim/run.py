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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim.run")
    parser.add_argument("--scenario", required=True, choices=sorted(REGISTRY))
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--out", default="reports/sim/")
    args = parser.parse_args(argv)
    if args.seeds <= 0:
        raise SystemExit("--seeds must be > 0")
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
    return 0 if payload["pass"] in (True, "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
