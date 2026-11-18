#!/usr/bin/env python3
"""Per-mint coverage progress and ETA to min_coverage (issue #231). Read-only."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.market_data import Sample, coverage  # noqa: E402
from index.params import IndexParams, frac  # noqa: E402
from tools.run_index import _load_samples  # noqa: E402


def load_seed_mints(path: Path) -> list[str]:
    if not path.is_file():
        return []
    mints = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if text:
            mints.append(text)
    return mints


def compute_progress(
    mints: list[str],
    samples: list[Sample],
    now: int,
    params: IndexParams,
) -> list[dict]:
    window_seconds = params.window_hours * 3600
    bucket_seconds = params.sample_minutes * 60
    start = now - window_seconds
    target_cov = float(frac(params.min_coverage))

    samples_by_mint: dict[str, list[Sample]] = {}
    for s in samples:
        samples_by_mint.setdefault(s.mint, []).append(s)

    rows = []
    for mint in sorted(set(mints) | set(samples_by_mint.keys())):
        mint_samples = samples_by_mint.get(mint, [])
        sample_times = [s.t for s in mint_samples]
        cov = coverage(sample_times, start, now, bucket_seconds)
        hours_covered = cov * params.window_hours
        pct = (cov / target_cov) * 100 if target_cov > 0 else 100.0
        pct = min(100.0, pct)

        if cov >= target_cov:
            eta = "reached"
        elif not sample_times or cov == 0:
            eta = "never"
        else:
            first_t = min(sample_times)
            elapsed = now - first_t
            if elapsed <= 0:
                eta = "never"
            else:
                rate = cov / elapsed
                rem = target_cov - cov
                rem_sec = rem / rate
                eta_unix = now + int(rem_sec)
                eta = datetime.fromtimestamp(eta_unix, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        rows.append(
            {
                "mint": mint,
                "samples": len(mint_samples),
                "hours_covered": round(hours_covered, 2),
                "pct_threshold": round(pct, 1),
                "eta": eta,
            }
        )
    return rows


def format_table(rows: list[dict]) -> str:
    lines = [
        f"{'mint':<45} | {'samples':<7} | {'hours':<6} | {'% thresh':<8} | {'ETA UTC':<20}",
        f"{'-' * 45}-+-{'-' * 7}-+-{'-' * 6}-+-{'-' * 8}-+-{'-' * 20}",
    ]
    for r in rows:
        lines.append(
            f"{r['mint']:<45} | {r['samples']:<7} | "
            f"{r['hours_covered']:<6.1f} | {r['pct_threshold']:<7.1f}% | "
            f"{r['eta']:<20}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, now: int | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-mint coverage progress and ETA")
    parser.add_argument("--samples", default="data/index/samples")
    parser.add_argument("--params", default="index/params.json")
    parser.add_argument("--seed-mints", default="index/seed_mints.txt")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    params = IndexParams.model_validate(json.loads(Path(args.params).read_text()))
    samples = _load_samples(Path(args.samples))
    seed_mints = load_seed_mints(Path(args.seed_mints))
    current_now = now if now is not None else int(datetime.now(UTC).timestamp())

    rows = compute_progress(seed_mints, samples, current_now, params)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
