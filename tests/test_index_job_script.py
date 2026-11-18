"""Contract tests for ops/index-job/index-job.sh (issue #216).

The script runs unattended on the index host, so a silent edit could make it
leak the API key, sign a transaction, or publish to the wrong branch. These
tests pin the safety properties; ``bash -n`` is the syntax gate.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "index-job" / "index-job.sh"

# A command line, skipping blank lines and whole-line comments.
_ACTIVE = [
    line.strip()
    for line in SCRIPT.read_text().splitlines()
    if line.strip() and not line.strip().startswith("#")
]

_HELIUS_EXPANSION = re.compile(r"\$\{?HELIUS_API_KEY\b")
_OUTPUT_COMMAND = re.compile(r"^(?:echo|printf)\b")
_WRITE_COMMAND = re.compile(r"(?<![\w./-])(solana|spl-token|send)(?![\w.-])")
_GIT_PUSH = re.compile(r"\bgit(?:\s+-C\s+\S+)?\s+push\s+([^;\n]+)")


def test_strict_shell_mode() -> None:
    assert "set -euo pipefail" in _ACTIVE
    # xtrace would dump the sourced HELIUS_API_KEY to the journal.
    assert not [line for line in _ACTIVE if re.search(r"\bset\s+-[a-z]*x", line)]


def test_documented_env_knobs_and_defaults() -> None:
    text = SCRIPT.read_text()
    defaults = {
        "COIN_REPO": "/opt/coin",
        "COIN_INDEX_WORKTREE": "/var/lib/coin/index-data",
        "COIN_INDEX_ENV": "/etc/coin/index.env",
        "COIN_INDEX_LOCK": "/var/lib/coin/index-job.lock",
    }
    for name, default in defaults.items():
        assert f"{name}:-{default}" in text
    assert "--discover-pages" in text and "COIN_INDEX_DISCOVER_PAGES" in text


def test_seed_file_argument_is_passed() -> None:
    mint_lines = [line for line in _ACTIVE if "--mints-file" in line]
    assert len(mint_lines) == 1
    assert "COIN_INDEX_MINTS" in mint_lines[0]
    assert "seed_mints.txt" in mint_lines[0]


def test_api_key_is_never_printed() -> None:
    leaked = [
        line for line in _ACTIVE if _OUTPUT_COMMAND.search(line) and _HELIUS_EXPANSION.search(line)
    ]
    assert leaked == []
    # No environment dump either (the regex only matches a command, not index.env).
    dump = re.compile(r"(?:^|[;&|(]|\$\()\s*(?:printenv|env)\b")
    assert not [line for line in _ACTIVE if dump.search(line)]


def test_no_solana_or_send_write_commands() -> None:
    offenders = [line for line in _ACTIVE if _WRITE_COMMAND.search(line)]
    assert offenders == []


def test_pushes_only_to_index_data() -> None:
    pushes = [match.group(1).strip() for line in _ACTIVE for match in _GIT_PUSH.finditer(line)]
    assert pushes, "the hourly job must publish index/out"
    for destination in pushes:
        assert shlex.split(destination) == ["origin", "HEAD:index-data"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_script_parses_with_bash() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
