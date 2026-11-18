"""Coverage-time model for the hourly GTA index (#215).

INDEX_RULES §2: a candidate needs samples covering at least `min_coverage` of its
window (24 h) and coverage is counted on 5-minute buckets (`sample_minutes` = 5 in
`index/params.json`). The sample timer ticks every `sample_minutes`; a tick fills its
bucket unless the sample is missed.

Expected-value model, so the output is deterministic: no clock, no RNG, no network.

- A tick and a bucket line up one-to-one. For `sample_minutes >= bucket_minutes` the
  expected filled share of the window grows by `(1 - miss_rate) * bucket / interval`
  per hour of sampling; for `sample_minutes < bucket_minutes` a bucket receives
  `bucket / interval` ticks and stays empty only when every tick misses.
- Coverage stops growing once the sampler has run for a whole window, because the
  window slides. Its ceiling is therefore the same rate; a cadence whose ceiling is
  below `min_coverage` never becomes eligible and is reported as `math.inf`.
- A token younger than the window is measured over its whole life, so it is never
  slower than this table: these hours are the worst case, for an aged mint.

Usage (regenerates the table in reports/index_coverage_table.md):

    uv run python -m sim.index_coverage
"""

from __future__ import annotations

import math

WINDOW_HOURS = 24  # index/params.json window_hours
BUCKET_MINUTES = 5  # index/params.json sample_minutes: the coverage grid
MIN_COVERAGE = 0.5  # index/params.json min_coverage = "1/2"
INTERVALS = (5, 10, 15)
MISS_RATES = (0.0, 0.1, 0.3)


def _finite(value: object, name: str) -> float:
    """Float for a finite number; reject bools, NaN and infinity with a ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


def _positive(value: object, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be > 0, got {value!r}")
    return number


def _share(value: object, name: str) -> float:
    number = _finite(value, name)
    if not 0 <= number <= 1:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")
    return number


def _fill_rate(sample_minutes: float, missed: float, bucket_minutes: float) -> float:
    """Expected share of the window's buckets filled per hour of sampling."""
    filled = 1 - missed
    if filled == 0:
        return 0.0
    ticks = bucket_minutes / sample_minutes
    return filled * ticks if ticks <= 1 else 1 - (1 - filled) ** ticks


def hours_to_eligible(
    sample_minutes: float,
    miss_rate: float,
    min_coverage: float,
    *,
    window_hours: float = WINDOW_HOURS,
    bucket_minutes: float = BUCKET_MINUTES,
) -> float:
    """Expected hours of sampling before an aged mint reaches `min_coverage`.

    `math.inf` when the cadence and miss rate can never fill that share of the window
    (the ceiling is the tick's bucket occupancy), and `0.0` when `min_coverage` is 0.
    Pure: same arguments, same float, every time.
    """
    interval = _positive(sample_minutes, "sample_minutes")
    missed = _share(miss_rate, "miss_rate")
    coverage = _share(min_coverage, "min_coverage")
    window = _positive(window_hours, "window_hours")
    bucket = _positive(bucket_minutes, "bucket_minutes")

    if coverage == 0:
        return 0.0
    rate = _fill_rate(interval, missed, bucket)
    if rate == 0 or coverage > rate:
        return math.inf
    return coverage * window / rate


def _hours_cell(hours: float) -> str:
    return "never" if math.isinf(hours) else f"{hours:.1f} h"


def _share_cell(share: float) -> str:
    return f"{share * 100:.0f}%"


def _markdown_table() -> str:
    """Hours to `MIN_COVERAGE`: one row per sampling cadence, one column per miss rate."""
    lines = [
        "| sample interval | 0% missed | 10% missed | 30% missed |",
        "|---|---|---|---|",
    ]
    for interval in INTERVALS:
        cells = [
            _hours_cell(hours_to_eligible(interval, miss, MIN_COVERAGE)) for miss in MISS_RATES
        ]
        lines.append(f"| {interval} min | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _ceiling_table() -> str:
    """Highest coverage each cadence can hold, i.e. why some rows say `never`."""
    lines = [
        "| sample interval | 0% missed | 10% missed | 30% missed |",
        "|---|---|---|---|",
    ]
    for interval in INTERVALS:
        cells = [_share_cell(_fill_rate(interval, miss, BUCKET_MINUTES)) for miss in MISS_RATES]
        lines.append(f"| {interval} min | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    print(_markdown_table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
