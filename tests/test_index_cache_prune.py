import os
import subprocess
import sys
from pathlib import Path

from adapters.index_history_cache import disk_used_pct, prune_cache_dir

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "prune_index_cache.py"


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


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the prune tool as the hourly job does: a plain script, no PYTHONPATH set."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_runs_as_a_script_from_any_cwd(tmp_path):
    """#308: the job's `uv run python tools/prune_index_cache.py` died with
    ModuleNotFoundError: No module named 'adapters', so the prune never happened."""
    cache = tmp_path / "cache"
    cache.mkdir()
    p = _run_cli(str(SCRIPT), "--cache-dir", str(cache), "--disk-path", str(tmp_path), cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    assert "pruned 0 cache files" in p.stdout
    assert "ModuleNotFoundError" not in p.stderr


def test_cli_runs_from_repo_root_like_the_job(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    p = _run_cli(
        "tools/prune_index_cache.py",
        "--cache-dir",
        str(cache),
        "--disk-path",
        str(tmp_path),
        cwd=ROOT,
    )
    assert p.returncode == 0, p.stderr
    assert "pruned 0 cache files" in p.stdout


def test_cli_warns_and_exits_3_above_threshold(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    p = _run_cli(
        str(SCRIPT),
        "--cache-dir",
        str(cache),
        "--disk-path",
        str(tmp_path),
        "--warn-pct",
        "0",
        cwd=tmp_path,
    )
    assert p.returncode == 3
    assert "WARNING: disk" in p.stderr
