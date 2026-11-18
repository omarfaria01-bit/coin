"""Prune data/index/cache (age + size cap) and warn when the disk is >= 85% used.

Usage: uv run python tools/prune_index_cache.py [--cache-dir D] [--disk-path P]
Exit 0 normally; exit 3 if disk usage is still >= the warn threshold after pruning.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Run as a script ("python tools/prune_index_cache.py"), sys.path[0] is tools/, so the repo
# root must be added or "import adapters" fails. That made the hourly prune a no-op inside
# `|| true`: the cache grew past the cap and the disk filled (#308).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.index_history_cache import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_MAX_TOTAL_BYTES,
    DISK_WARN_PCT,
    disk_used_pct,
    prune_cache_dir,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_SECONDS / 3600)
    ap.add_argument("--max-total-mb", type=float, default=DEFAULT_MAX_TOTAL_BYTES / 1e6)
    ap.add_argument("--disk-path", default=".")
    ap.add_argument("--warn-pct", type=float, default=DISK_WARN_PCT)
    a = ap.parse_args()
    removed = prune_cache_dir(
        time.time(), a.cache_dir, int(a.max_age_hours * 3600), int(a.max_total_mb * 1e6)
    )
    pct = disk_used_pct(a.disk_path)
    print(f"pruned {len(removed)} cache files; disk {pct:.1f}% used")
    if pct >= a.warn_pct:
        print(f"WARNING: disk {pct:.1f}% >= {a.warn_pct:.0f}%", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
