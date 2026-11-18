"""Pytest configuration and autouse fixtures for cache isolation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("COIN_MIN_FREE_BYTES", "1")


@pytest.fixture(autouse=True)
def _clean_index_cache() -> None:
    cache_dir = Path("data/index/cache")
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    yield
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
