"""Incremental history cache for mint transaction history under data/index/cache/."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from adapters.helius_client import HeliusClient
from adapters.helius_parse import slim_item

log = logging.getLogger(__name__)
DEFAULT_CACHE_DIR = Path("data/index/cache")
SCHEMA_VERSION = 1
DEFAULT_WINDOW_SECONDS = 7 * 86_400  # 7 days
MIN_FREE_BYTES = int(
    os.environ.get("COIN_MIN_FREE_BYTES", "1_000_000_000")
)  # #311: below 1 GB free, skip the write (cache is only a speed-up)


def _cache_path(mint: str, cache_dir: Path | None = None) -> Path:
    d = cache_dir or DEFAULT_CACHE_DIR
    return d / f"{mint}.json"


def load_cache(
    mint: str, cache_dir: Path | None = None
) -> tuple[list[dict[str, Any]], bool] | None:
    """Load cached history for mint.

    Returns (transactions, truncated) or None on miss/corruption/schema mismatch.
    """
    path = _cache_path(mint, cache_dir)
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, OSError, UnicodeError):
        log.warning("Cache corrupt or unreadable for mint %s", mint)
        return None

    if not isinstance(data, dict):
        return None
    if data.get("schema") != SCHEMA_VERSION:
        return None
    if data.get("mint") != mint:
        return None
    txs = data.get("transactions")
    if not isinstance(txs, list):
        return None
    truncated = bool(data.get("truncated", False))
    valid_txs = [tx for tx in txs if isinstance(tx, dict)]
    return valid_txs, truncated


KEEP_MIN = 1000


def _block_time(tx: dict[str, Any]) -> int | None:
    for value in (
        tx.get("block_time"),
        tx.get("blockTime"),
        tx.get("timestamp"),
        (tx.get("parsed") or {}).get("blockTime") if isinstance(tx.get("parsed"), dict) else None,
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def save_cache(
    mint: str,
    transactions: list[dict[str, Any]],
    truncated: bool,
    as_of: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    cache_dir: Path | None = None,
) -> None:
    """Save history to cache, pruning transactions older than as_of - window_seconds."""
    d = cache_dir or DEFAULT_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)

    cutoff = as_of - window_seconds
    pruned: list[dict[str, Any]] = []
    for i, tx in enumerate(transactions):
        if not isinstance(tx, dict):
            continue
        bt = _block_time(tx)
        # D37: raw rows carry parsed.blockTime (block_time was never set, so nothing was pruned
        # and the cache grew to 1.6G). Keep the window, or at least the newest KEEP_MIN rows.
        if isinstance(bt, int) and bt < cutoff and i >= KEEP_MIN:
            truncated = True  # older rows dropped: lifetime sums become lower bounds
            continue
        pruned.append(slim_item(tx))  # #311: only the fields normalize_transaction reads

    try:
        free = shutil.disk_usage(d).free
    except OSError:
        free = None
    if free is not None and free < MIN_FREE_BYTES:
        log.warning("Low disk (%d bytes free): cache for mint %s not written", free, mint)
        return

    payload = {
        "schema": SCHEMA_VERSION,
        "mint": mint,
        "truncated": truncated,
        "transactions": pruned,
    }
    path = _cache_path(mint, cache_dir)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("Failed to write cache for mint %s: %s", mint, exc)
    finally:
        # #311: a failed write (ENOSPC) must never leave a partial ~200 MB .tmp behind.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def fetch_mint_history_incremental(
    client: HeliusClient,
    mint: str,
    *,
    as_of: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch mint history incrementally using cache.

    1. Load cache.
    2. If miss/corrupt/mismatch, do full fetch and cache.
    3. If hit, fetch newest-first stopping when a page's oldest signature is cached.
    4. Merge cached + new, deduplicate by signature, prune, save, and return.
    """
    cached = load_cache(mint, cache_dir)
    if cached is None:
        raw, truncated = client.history(mint, end=as_of)
        save_cache(mint, raw, truncated, as_of, window_seconds, cache_dir)
        return raw, truncated

    cached_txs, cached_truncated = cached
    cached_sigs = {
        tx.get("signature")
        for tx in cached_txs
        if isinstance(tx, dict) and isinstance(tx.get("signature"), str)
    }

    raw, truncated = client.history(mint, end=as_of, stop_on_cached=cached_sigs)

    seen: set[str] = set()
    combined: list[dict[str, Any]] = []

    for tx in raw:
        if not isinstance(tx, dict):
            continue
        sig = tx.get("signature")
        if isinstance(sig, str):
            if sig not in seen:
                seen.add(sig)
                combined.append(tx)
        else:
            combined.append(tx)

    for tx in cached_txs:
        if not isinstance(tx, dict):
            continue
        sig = tx.get("signature")
        if isinstance(sig, str):
            if sig not in seen:
                seen.add(sig)
                combined.append(tx)
        else:
            combined.append(tx)

    truncated = truncated or bool(cached_truncated)  # D37: pruned history is a lower bound
    save_cache(mint, combined, truncated, as_of, window_seconds, cache_dir)
    return combined, truncated


DEFAULT_MAX_AGE_SECONDS = 48 * 3600
DEFAULT_MAX_TOTAL_BYTES = 1_000_000_000  # #311: was 1.5 GB
DISK_WARN_PCT = 85.0


def prune_cache_dir(
    now: float,
    cache_dir: Path | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> list[Path]:
    """Delete cache files not written for max_age_seconds, then oldest-first until the
    directory is <= max_total_bytes. The cache is only an accelerator; a miss means a full
    refetch, so deleting is always safe. Returns removed paths. Uses file mtimes."""
    d = cache_dir or DEFAULT_CACHE_DIR
    if not d.is_dir():
        return []
    entries: list[tuple[float, int, Path]] = []
    for p in d.iterdir():
        if p.is_file() and p.suffix in (".json", ".tmp"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, p))
    removed: list[Path] = []
    keep: list[tuple[float, int, Path]] = []
    for mtime, size, p in entries:
        if now - mtime > max_age_seconds:
            try:
                p.unlink()
                removed.append(p)
            except OSError:
                keep.append((mtime, size, p))
        else:
            keep.append((mtime, size, p))
    total = sum(size for _, size, _ in keep)
    for _mtime, size, p in sorted(keep):  # oldest first
        if total <= max_total_bytes:
            break
        try:
            p.unlink()
            removed.append(p)
            total -= size
        except OSError:
            continue
    return removed


def disk_used_pct(path: str | os.PathLike[str] = ".") -> float:
    """Percent of the filesystem containing path that is used."""
    u = shutil.disk_usage(path)
    return 100.0 * u.used / u.total if u.total else 0.0
