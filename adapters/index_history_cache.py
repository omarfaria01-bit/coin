"""Incremental history cache for mint transaction history under data/index/cache/."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from adapters.helius_client import HeliusClient

log = logging.getLogger(__name__)
DEFAULT_CACHE_DIR = Path("data/index/cache")
SCHEMA_VERSION = 1
DEFAULT_WINDOW_SECONDS = 7 * 86_400  # 7 days


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
        pruned.append(tx)

    payload = {
        "schema": SCHEMA_VERSION,
        "mint": mint,
        "truncated": truncated,
        "transactions": pruned,
    }
    path = _cache_path(mint, cache_dir)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("Failed to write cache for mint %s: %s", mint, exc)


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
