"""#85: parameter variants for kiwi on the real engine (COIN_MATH §3, §4, §2, §9). Defaults are
NOT changed here; every variant is a CoinParams copy, run on the same seeds as the default.

    uv run python -m sim.variants_v033 --seeds 3   # → reports/variants_v033_<date>.md (tables)

The Italian summary and recommendation at the top of the committed report are written by hand
from these tables.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from statistics import mean

import sim.acceptance_v033 as acc
from engine.params import CoinParams
from sim import outputs_v033 as out
from sim.population_v033 import Run, simulate
from sim.report_v033 import _stability, _with

H = 3_600
D = 24 * H
DEFAULT = CoinParams()
OLD = ((48 * H, "1"), (30 * D, "2"))  # v0.2 shape: start 48h, 2.0× at 30d, flat after
MIDDLE = ((12 * H, "1"), (D, "21/20"), (7 * D, "3/2"), (30 * D, "2"), (90 * D, "47/20"))

VARIANTS: dict[str, tuple[str, CoinParams]] = {
    "default": ("curve", DEFAULT),
    "curve old (48h, 2.0× @30d)": (
        "curve", _with(DEFAULT, hold={"knots": OLD, "t_start_seconds": 48 * H})),
    "curve middle (12h … 2.35× @90d)": (
        "curve", _with(DEFAULT, hold={"knots": MIDDLE, "t_start_seconds": 12 * H})),
    "T_START 2h (old default)": ("t_start", _with(DEFAULT, hold={"t_start_seconds": 2 * H})),
    "T_START 12h": ("t_start", _with(DEFAULT, hold={"t_start_seconds": 12 * H})),
    "T_START 48h": ("t_start", _with(DEFAULT, hold={"t_start_seconds": 48 * H})),
    "eligibility 1/10,000,000": (
        "share", _with(DEFAULT, eligibility={"min_eligible_share": "1/10000000"})),
    "eligibility 1/100,000": (
        "share", _with(DEFAULT, eligibility={"min_eligible_share": "1/100000"})),
}  # fmt: skip
DRAW_VARIANTS = (("weekly n=7, δ=1 (default)", 7, 1.0), ("3-day n=3, δ=1/2", 3, 0.5),
                 ("daily n=1, δ=1/3", 1, 1 / 3))  # fmt: skip


@contextmanager
def rows_under(params: CoinParams) -> Iterator[None]:
    old, acc.PARAMS = acc.PARAMS, params
    try:
        yield
    finally:
        acc.PARAMS = old


def row_failures(params: CoinParams, seeds: int) -> list[str]:
    """Names of the §14 rows (acceptance + attack) that fail on any seed under `params`."""
    with rows_under(params):
        return [r.name for r in acc.run_rows(seeds) if r.passed < r.seeds]


def measure(runs: list[Run]) -> dict[str, float]:
    m: dict[str, list[float]] = {}

    def put(k: str, v: float) -> None:
        m.setdefault(k, []).append(v)

    for r in runs:
        for k, v in out.retention(r).items():
            put(k, v)
        c = out.concentration(r)
        put("top10_d60_90", c[-1] if c else 0.0)
        put("loyal_vs_farmer", out.loyal_vs_farmer(r))
        s = out.small_holder(r, draw_samples=500)
        put("small_share", s["share"])
        put("small_days_to_first_payout", s["days_to_first_payout"])
        rate = out.rate_by_holding(r)
        put("trader4h_vs_7d", rate[4] / rate[168] if rate[168] else 0)
    return {k: mean(v) for k, v in m.items()}


def draw_table(runs: list[Run]) -> list[tuple[str, float, float, float]]:
    """€100 holder: odds per draw, draws per 30d, P(≥ 1 prize in 30 days)."""
    rows = []
    for name, n, _delta in DRAW_VARIANTS:
        p = mean(out._draw_odds(r, _small(r), n, 1_000) for r in runs)
        k = 30 / n
        rows.append((name, p, k, 1 - (1 - p) ** k))
    return rows


def _small(r: Run) -> str:
    return next(a.wallet for a in r.agents if a.kind == "small")


def build(seeds: int, days: int = 93, stability: bool = True) -> str:
    table, fails, stab = [], {}, {}
    base_runs: list[Run] = []
    for name, (_group, params) in VARIANTS.items():
        runs = [simulate(s, params, days=days) for s in range(seeds)]
        base_runs = base_runs or runs
        table.append((name, measure(runs)))
        fails[name] = row_failures(params, seeds)
        stab[name] = _stability(0, runs[0], params)[1] if stability else "not run"
    cols = ["retained_30d", "retained_60d", "retained_90d", "balance_90d", "sold_after_30d",
            "sold_after_60d", "top10_d60_90", "loyal_vs_farmer", "small_share",
            "small_days_to_first_payout", "trader4h_vs_7d"]  # fmt: skip
    md = ["| variant | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, m in table:
        md.append(f"| {name} | " + " | ".join(f"{m.get(c, 0):.3f}" for c in cols) + " |")
    rows_md = ["| variant | §14 rows failing (of 23) | stability (seed 0) |", "|---|---|---|"]
    for name in VARIANTS:
        f = ", ".join(fails[name]) or "none"
        rows_md.append(f"| {name} | {len(fails[name])}: {f} | {stab[name]} |")
    draws_md = ["| draw period | €100 odds per draw | draws / 30d | P(≥ 1 prize in 30d) |",
                "|---|---|---|---|"]  # fmt: skip
    for name, p, k, p30 in draw_table(base_runs):
        draws_md.append(f"| {name} | {p:.3f} | {k:.0f} | {p30:.3f} |")
    return (
        f"# v0.3.3 variants for kiwi (#85), {dt.date.today().isoformat()}\n\n"
        f"Seeds 0–{seeds - 1} for every variant, {days} epochs, the population in "
        "`sim.population_v033` (modelled agents: comparisons between designs, not forecasts; "
        "no APR or yield). Defaults unchanged.\n\n## Outcomes (mean over seeds)\n\n"
        + "\n".join(md)
        + "\n\n## §14 rows per variant\n\n"
        + "\n".join(rows_md)
        + "\n\n## Draw period (draws are off at launch, D19)\n\n"
        + "\n".join(draws_md)
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sim.variants_v033")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    random.seed(0)
    path = Path(args.out or f"reports/variants_v033_{dt.date.today().isoformat()}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(args.seeds), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
