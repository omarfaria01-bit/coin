"""#311 follow-up: the prune script must import when run as a plain script (systemd/cron)."""

import subprocess  # nosec B404
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "prune_index_cache.py"


def test_prune_script_runs_from_another_cwd(tmp_path):
    r = subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), "--cache-dir", str(tmp_path / "c")]
        + ["--disk-path", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "ModuleNotFoundError" not in r.stderr
    assert r.returncode in (0, 3), r.stderr
    assert "pruned 0 cache files" in r.stdout
