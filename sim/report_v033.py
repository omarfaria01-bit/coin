"""`reports/sim_<date>.md`: every COIN_MATH §14 row as PASS, FAIL or GAP, plus the §14 outputs
from the population runs (#84 step 3b).

    uv run python -m sim.run --report --seeds 3            # exit 1 if any row fails
    uv run python -m sim.run --report --seeds 3 --strict   # also exit 1 while a GAP is left
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from statistics import mean

from engine.params import CoinParams
from sim import outputs_v033 as out
from sim.acceptance_v033 import RowResult, render, run_rows
from sim.population_v033 import INFLOW, Run, simulate

# §14 rows not implemented yet, with their category and reason (#133). A row is closed by
# adding it to sim.acceptance_v033.all_rows / population_rows; the list may only shrink.
# a = off at launch by a D19/§16 flag (boost, draws, bot); b = offline-able but not written
# or needs a component that does not exist yet.
GAPS: tuple[tuple[str, str, str], ...] = (
    ("Same split, boost on", "a", "underwater boost off at launch (D19); run_epoch rejects it"),
    ("Underwater farmer", "a", "boost off (D19)"),
    ("Holding the pool lower for ≤ 1h (P̄_e)", "a", "P̄_e feeds only the boost, off (D19)"),
    ("Two RPC sources disagree", "b",
     "needs the P4 adapter's dual-source client; the engine has no single-source finalize path"),
    ("Draw payout / draw fairness (χ²)", "a", "draws off at launch (D19); sampler unit-tested"),
    ("Multiplier ≤ 4.2× with boost", "a", "boost off (D19)"),
    ("Informed agent vs. simple holder", "b",
     "needs an optimising agent; a strategy search over the curve is not an offline fixture"),
    ("Independent implementation", "b",
     "separate Rust/TS deliverable outside this repo (COIN_MATH §14), not a sim row"),
    ("Treasury bot backtest", "a", "bot off at launch (D19); needs real price paths"),
)  # fmt: skip
CATEGORY = {"a": "a · D19 flag", "b": "b · offline"}


STABILITY: tuple[tuple[str, Callable[[CoinParams, Fraction], CoinParams]], ...] = (
    ("cap", lambda p, f: _with(p, scoring={"cap": float(Fraction(str(p.scoring.cap)) * f)})),
    ("T_START", lambda p, f: _with(p, hold={"t_start_seconds": int(p.hold.t_start_seconds * f)})),
    (
        "MIN_ELIGIBLE_SHARE",
        lambda p, f: _with(
            p,
            eligibility={"min_eligible_share": str(Fraction(p.eligibility.min_eligible_share) * f)},
        ),
    ),  # fmt: skip
    (
        "curve slope (h − 1)",
        lambda p, f: _with(
            p, hold={"knots": tuple((a, str(1 + (Fraction(h) - 1) * f)) for a, h in p.hold.knots)}
        ),
    ),  # fmt: skip
)


def _with(p: CoinParams, **sections: dict) -> CoinParams:
    data = p.model_dump(mode="json")
    for k, v in sections.items():
        data[k] = {**data[k], **v}
    return CoinParams.model_validate(data)


def population_rows(runs: list[Run], params: CoinParams) -> list[RowResult]:
    """§14 rows that need many epochs, judged on the same population seeds."""
    rows = []

    def add(name: str, cond: str, results: list[tuple[bool, str]]) -> None:
        fails = [(i, e) for i, (ok, e) in enumerate(results) if not ok]
        i, e = fails[0] if fails else (0, results[0][1])
        rows.append(
            RowResult(name, cond, len(results) - len(fails), len(results), f"seed {i}: {e}")
        )

    def trader(r: Run):
        rate = out.rate_by_holding(r)
        x = rate[4] / rate[168]
        return x <= 0.30, f"4h/7d reward per token-hour = {x:.3f}"

    def conc(seed: int):
        c = out.concentration(simulate(seed, params, days=runs[seed].days, stable=True))
        if len(c) < 3:
            return True, f"n/a: {len(c)} full 30-day windows"
        return c[-1] <= c[-2] + 1e-9, "top-10% per 30d: " + " → ".join(f"{x:.3f}" for x in c)

    add(
        "Trader in 4h cycles vs a 7-day holder",
        "reward per token-hour ≤ 30%",
        [trader(r) for r in runs],
    )
    add(
        "Reward concentration",
        "stable holders: top-10% share not rising day 60 → 90",
        [conc(s) for s in range(len(runs))],
    )
    seeds = range(len(runs))
    add("Reward stability (first target)", "±10% on one param moves no honest share > 15%",
        [_stability(s, runs[s], params) for s in seeds])  # fmt: skip
    add("Volume −90% overnight", "payouts ≥ 45% of the prior level after 7 days",
        [_volume_drop(s, params) for s in seeds])  # fmt: skip
    add("Higher multiplier vs. concentration", "2.8× top-10% ≤ 2.0× + 5 points (first target)",
        [_multiplier_conc(s, runs[s], params) for s in seeds])  # fmt: skip
    return rows


# v0.2 shape: start 48h, 2.0× at 30d, flat after (the "2.0× curve" in §14).
OLD_CURVE = ((48 * 3_600, "1"), (30 * 86_400, "2"))


def _multiplier_conc(seed: int, base: Run, params: CoinParams) -> tuple[bool, str]:
    """§14: with the 2.8× curve, the top-10% reward share is not more than 5 points above
    the 2.0× curve's, on the same population and the last 30-day window."""
    if base.days < 60:
        return True, f"n/a: {base.days}-day run (needs a full 60–90 window)"
    two = _with(params, hold={"knots": OLD_CURVE, "t_start_seconds": 48 * 3_600})
    hi = out.concentration(base)[-1]
    lo = out.concentration(simulate(seed, two, days=base.days))[-1]
    return hi <= lo + 0.05, f"top-10% 2.8×={hi:.3f} 2.0×={lo:.3f} Δ={hi - lo:+.3f}"


def _stability(seed: int, base: Run, params: CoinParams) -> tuple[bool, str]:
    ref, worst, where = out.honest_shares(base), 0.0, ""
    for name, mod in STABILITY:
        for f in (Fraction(9, 10), Fraction(11, 10)):
            new = out.honest_shares(simulate(seed, mod(params, f), days=base.days))
            for w, s in ref.items():
                move = abs(new.get(w, 0) - s) / s if s else 0
                if move > worst:
                    worst, where = move, f"{name} ×{float(f):.1f}"
    return worst <= 0.15, f"max move {worst:.1%} ({where})"


def _volume_drop(seed: int, params: CoinParams, at: int = 60) -> tuple[bool, str]:
    r = simulate(seed, params, days=at + 8, inflow=lambda d: INFLOW if d < at else INFLOW // 10)
    before = sum(r.results[at - 1].payouts.values())
    after = sum(r.results[at + 7].payouts.values())
    x = after / before if before else 0
    return x >= 0.45, f"day {at + 7} / day {at - 1} payouts = {x:.3f}"


def outputs_md(runs: list[Run]) -> str:
    def stat(xs: list[float], fmt: str = "{:.3f}") -> str:
        return f"{fmt.format(mean(xs))} (min {fmt.format(min(xs))}, max {fmt.format(max(xs))})"

    lines = ["| output | mean over seeds (min, max) |", "|---|---|"]
    dists = [out.distribution(r) for r in runs]
    for k in dists[0]:
        lines.append(
            f"| rewards {k} {'(SOL)' if k[0] == 'p' else ''} | {stat([d[k] for d in dists])} |"
        )
    conc = [out.concentration(r) for r in runs]
    for i in range(len(conc[0])):
        lines.append(
            f"| top-10% share, days {30 * i}–{30 * i + 30} | {stat([c[i] for c in conc])} |"
        )
    rates = [out.rate_by_holding(r) for r in runs]
    for h in rates[0]:
        lines.append(
            f"| lamports per token-hour, {h}h holds | {stat([x[h] for x in rates], '{:.2f}')} |"
        )
    small = [out.small_holder(r) for r in runs]
    for k in small[0]:
        lines.append(f"| €100 holder: {k} | {stat([s[k] for s in small], '{:.4f}')} |")
    ret = [out.retention(r) for r in runs]
    for k in ret[0]:
        lines.append(f"| cohort {k} | {stat([x[k] for x in ret])} |")
    lines.append(
        f"| loyal ÷ farmer reward per token | {stat([out.loyal_vs_farmer(r) for r in runs])} |"
    )
    return "\n".join(lines) + "\n"


def build(seeds: int, days: int = 93) -> tuple[str, list[RowResult]]:
    params = CoinParams()
    rows = run_rows(seeds)
    runs = [simulate(s, params, days=days) for s in range(seeds)]
    rows += population_rows(runs, params)
    n_fail = sum(r.passed < r.seeds for r in rows)
    gap_md = "\n".join(f"| {n} | {CATEGORY[k]} | GAP | {why} |" for n, k, why in GAPS)
    text = (
        f"# COIN_MATH v0.3.3 §14 simulator report\n\nSeeds: {seeds} per row; population: {days} "
        f"epochs, modelled agents (comparisons, not forecasts), default params.\n\n"
        f"**{len(rows) - n_fail} PASS · {n_fail} FAIL · {len(GAPS)} GAP**\n\n## Rows\n\n"
        f"{render(rows)}\n## Gaps (not implemented yet)\n\n"
        f"| §14 row | category | status | reason |\n|---|---|---|---|\n{gap_md}\n\n"
        f"## Outputs\n\n{outputs_md(runs)}"
    )
    return text, rows


def main(seeds: int, out_path: str | None, strict: bool) -> int:
    text, rows = build(seeds)
    path = Path(out_path or f"reports/sim_{dt.date.today().isoformat()}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text, end="")
    failed = any(r.passed < r.seeds for r in rows)
    return 1 if failed or (strict and GAPS) else 0
