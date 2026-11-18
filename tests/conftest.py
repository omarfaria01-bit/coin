"""Pytest configuration and autouse fixtures for cache isolation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_index_cache() -> None:
    cache_dir = Path("data/index/cache")
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    yield
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
