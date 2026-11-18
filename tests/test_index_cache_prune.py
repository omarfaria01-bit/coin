import os

from adapters.index_history_cache import disk_used_pct, prune_cache_dir


def _mk(d, name, size, age_h, now):
    p = d / name
    p.write_bytes(b"x" * size)
    t = now - age_h * 3600
    os.utime(p, (t, t))
    return p


def test_prune_by_age(tmp_path):
    now = 1_000_000_000.0
    old = _mk(tmp_path, "a.json", 10, 49, now)
    new = _mk(tmp_path, "b.json", 10, 1, now)
    other = _mk(tmp_path, "keep.txt", 10, 99, now)
    removed = prune_cache_dir(now, tmp_path)
    assert removed == [old] and new.exists() and other.exists()


def test_prune_by_size_oldest_first(tmp_path):
    now = 1_000_000_000.0
    a = _mk(tmp_path, "a.json", 100, 10, now)
    b = _mk(tmp_path, "b.json", 100, 5, now)
    c = _mk(tmp_path, "c.json", 100, 1, now)
    removed = prune_cache_dir(now, tmp_path, max_total_bytes=150)
    assert removed == [a, b] and c.exists()


def test_prune_missing_dir_and_disk_pct(tmp_path):
    assert prune_cache_dir(0.0, tmp_path / "nope") == []
    assert 0.0 <= disk_used_pct(tmp_path) <= 100.0
