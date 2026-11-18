"""Incremental per-mint history cache (#247). Same result as a full fetch, fewer requests.

The cache holds the raw parsed rows of a COMPLETE (not page-capped) history up to `as_of`.
Next run fetches newest-first and stops at the first cached signature, then appends the cache.
Anything doubtful (missing, corrupt, wrong schema, too old, clock went back) is a full fetch.
Files live under data/index/cache/ (git-ignored). Nothing here touches engine/ or logs a key.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from adapters.helius_client import HeliusClient

SCHEMA = 1
_SAFE = re.compile(r"^[A-Za-z0-9]{1,64}$")


class HistoryCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, address: str) -> Path | None:
        return self.root / f"{address}.json" if _SAFE.match(address) else None

    def load(self, address: str, *, as_of: int, max_age: int) -> list[dict[str, object]] | None:
        path = self._path(address)
        if path is None or not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text())
            rows, saved = doc["rows"], doc["as_of"]
            ok = doc["schema"] == SCHEMA and doc["address"] == address
            ok = ok and isinstance(rows, list) and isinstance(saved, int)
            ok = ok and not isinstance(saved, bool)
            ok = ok and all(
                isinstance(r, dict) and isinstance(r.get("signature"), str) for r in rows
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        # never reuse data past the window, or from the future of this run
        if not ok or saved > as_of or as_of - saved > max_age:
            return None
        return rows

    def save(self, address: str, rows: list[dict[str, object]], *, as_of: int) -> None:
        path = self._path(address)
        if path is None:
            return
        doc = {"schema": SCHEMA, "address": address, "as_of": as_of, "rows": rows}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":")))
            os.replace(tmp, path)
        except OSError:
            return  # a cache that cannot be written is just a cache miss next time


def cached_history(
    client: HeliusClient,
    cache: HistoryCache | None,
    address: str,
    *,
    as_of: int,
    max_age: int,
) -> tuple[list[dict[str, object]], bool]:
    """Equal to `client.history(address, end=as_of)`, using the cache when it is safe."""
    if cache is None:
        return client.history(address, end=as_of)
    old = cache.load(address, as_of=as_of, max_age=max_age)
    if not old:
        rows, truncated = client.history(address, end=as_of)
    else:
        known = {str(r["signature"]) for r in old}
        new, truncated, hit = client.history_new(address, known=known, end=as_of)
        rows = new + old if hit else new
        if not hit and not truncated:
            rows = new  # walked to the end without meeting the cache: nothing to merge
    if not truncated:  # a capped history is not a complete base for the next run
        cache.save(address, rows, as_of=as_of)
    return rows, truncated
