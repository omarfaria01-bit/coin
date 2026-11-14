"""Vesting-margin sweep: unlocked fraction for a rectangular end-of-window pump.

Pure arithmetic over engine.vesting.unlocked_fraction. No randomness, no I/O
except writing the markdown report when invoked as a module.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from engine.params import VestingParams
from engine.vesting import unlocked_fraction

K_VALUES: tuple[float, ...] = (2.0, 2.5, 3.0, 3.1, 3.5, 4.0)
WINDOWS_H: tuple[int, ...] = (6, 12, 24, 36)
DURATIONS_H: tuple[float, ...] = (0.5, 1.0, 2.0)
UNLOCK_LIMIT = 0.05
_ENTRY = 100.0
DEFAULT_REPORT = Path("reports/vesting_twap_sweep.md")


def pump_twap(entry: float, k: float, duration_h: float, window_h: int) -> float:
    """TWAP of ``window_h - duration_h`` at ``entry`` and ``duration_h`` at ``k * entry``."""
    if window_h <= 0:
        raise ValueError(f"window_h must be positive, got {window_h}")
    if duration_h < 0 or duration_h > window_h:
        raise ValueError(f"duration_h must be in [0, window_h], got {duration_h}")
    rest = window_h - duration_h
    return (rest * entry + duration_h * k * entry) / window_h


def unlocked_for(
    k: float,
    duration_h: float,
    window_h: int,
    params: VestingParams | None = None,
) -> float:
    """Unlocked fraction at t = t0 (u_time = 0) after a rectangular end-of-window pump."""
    p = VestingParams() if params is None else params
    twap = pump_twap(_ENTRY, k, duration_h, window_h)
    return unlocked_fraction(0.0, 0, 0, twap, _ENTRY, p)


def smallest_safe_window(
    k: float,
    duration_h: float = 1.0,
    windows: Sequence[int] = WINDOWS_H,
    limit: float = UNLOCK_LIMIT,
    params: VestingParams | None = None,
) -> int | None:
    """Smallest window in ``windows`` whose unlocked fraction stays strictly under ``limit``."""
    for window_h in windows:
        if unlocked_for(k, duration_h, window_h, params) < limit:
            return window_h
    return None


def _fmt(value: float, *, mark: bool) -> str:
    text = f"{value:.4f}"
    return f"**{text}**" if mark and value >= UNLOCK_LIMIT else text


def _table(duration_h: float, mark_over: bool, params: VestingParams) -> list[str]:
    header = ["k \\\\ window"] + [f"{w}h" for w in WINDOWS_H]
    sep = ["---"] * len(header)
    rows = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for k in K_VALUES:
        cells = [f"{k:g}×"]
        for window_h in WINDOWS_H:
            u = unlocked_for(k, duration_h, window_h, params)
            cells.append(_fmt(u, mark=mark_over))
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def render_report(
    params: VestingParams | None = None,
    k_values: Iterable[float] = (3.1, 3.5),
) -> str:
    p = VestingParams() if params is None else params
    out: list[str] = [
        "# Vesting TWAP margin sweep",
        "",
        "Rectangular end-of-window pump: the last `duration` hours of a `window`-hour",
        "TWAP sit at `k × p_entry`, the rest of the window sits at `p_entry`.",
        "Unlocked fraction is `engine.vesting.unlocked_fraction(0, t=t0, …)` so only",
        "`u_price = ln(TWAP / p_entry) / ln(M)` contributes (defaults: M=5).",
        "",
        (
            "Cells in the **1h** table are **bold** when the unlocked "
            f"fraction is ≥ {UNLOCK_LIMIT:.0%}."
        ),
        "Defaults are not changed by this report (D14 stays a Claude decision).",
        "",
    ]
    for duration_h in DURATIONS_H:
        title = f"## Pump duration {duration_h:g}h"
        if duration_h == 1.0:
            title += " (cells ≥ 5% marked)"
        out.append(title)
        out.append("")
        out.extend(_table(duration_h, duration_h == 1.0, p))
        out.append("")

    out.append("## Smallest window that keeps a 1h pump under 5%")
    out.append("")
    for k in k_values:
        w = smallest_safe_window(k, 1.0, WINDOWS_H, UNLOCK_LIMIT, p)
        u = unlocked_for(k, 1.0, w, p) if w is not None else None
        if w is None:
            out.append(f"- 1h {k:g}×: no window in {list(WINDOWS_H)} stays under 5%.")
        else:
            out.append(
                f"- 1h {k:g}×: **{w}h** is the smallest window in the grid "
                f"(unlocked fraction {u:.4f} < 5%)."
            )
    out.append("")
    out.append(
        "A 1h 3× pump on the current 24h default is 0.0497, just under 5%. "
        "A 1h 3.1× or 3.5× pump needs the 36h window; 24h is not enough."
    )
    out.append("")
    return "\n".join(out)


def write_report(path: Path | None = None, params: VestingParams | None = None) -> Path:
    dest = DEFAULT_REPORT if path is None else Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_report(params), encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="sim.sweep")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    path = write_report(args.out)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
