"""Contract for ops/index-job/index-job.sh (issue #216): read-only, no key leaks, index-data only.

Each check is a function over the script text, so mutation tests can prove it fails when broken.
"""

import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ops/index-job/index-job.sh"
TEXT = SCRIPT.read_text()


def _code(text: str) -> list[str]:
    """Non-comment, non-blank lines (comments like 'never sends' must not hide or fake matches)."""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def check_strict_mode(text: str) -> None:
    assert "set -euo pipefail" in _code(text)


def check_mints_file(text: str) -> None:
    assert any("--mints-file" in ln for ln in _code(text))


def check_key_never_printed(text: str) -> None:
    code = _code(text)
    for ln in code:
        if re.search(r"\b(echo|printf|cat|env|printenv)\b", ln):
            assert not re.search(r"\$\{?HELIUS_API_KEY", ln), ln
        assert not re.search(r"\bset\s+-\w*x", ln), ln  # xtrace would print the key
    assert not any("xtrace" in ln for ln in code)


def check_no_write_commands(text: str) -> None:
    for ln in _code(text):
        assert not re.search(r"\b(solana|spl-token|send\w*)\b", ln, re.I), ln


def check_push_only_index_data(text: str) -> None:
    pushes = [ln for ln in _code(text) if re.search(r"\bgit\b.*\bpush\b", ln)]
    assert pushes, "expected the publish step to push"
    for ln in pushes:
        assert re.search(r"HEAD:index-data\b", ln), ln
        assert not re.search(r"--force|--mirror|--all|\s-f\b|\s\+", ln), ln


CHECKS = [
    check_strict_mode,
    check_mints_file,
    check_key_never_printed,
    check_no_write_commands,
    check_push_only_index_data,
]


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_script_satisfies_contract(check):
    check(TEXT)


def test_bash_syntax_ok():
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _drop(text: str, needle: str) -> str:
    assert needle in text, needle
    return "\n".join(ln for ln in text.splitlines() if needle not in ln)


MUTATIONS = [
    (check_strict_mode, lambda t: _drop(t, "set -euo pipefail")),
    (check_mints_file, lambda t: _drop(t, "--mints-file")),
    (check_key_never_printed, lambda t: t + '\necho "key=$HELIUS_API_KEY"\n'),
    (check_key_never_printed, lambda t: t.replace("set -euo", "set -x\nset -euo", 1)),
    (check_no_write_commands, lambda t: t + "\nsolana transfer a b 1\n"),
    (check_no_write_commands, lambda t: t + "\nspl-token transfer m 1 a\n"),
    (check_push_only_index_data, lambda t: t.replace("HEAD:index-data", "HEAD:main")),
    (check_push_only_index_data, lambda t: t + "\ngit push --force origin HEAD:index-data\n"),
    (check_push_only_index_data, lambda t: _drop(t, "push origin HEAD:index-data")),
]


@pytest.mark.parametrize("check,mutate", MUTATIONS)
def test_each_check_fails_when_line_is_broken(check, mutate):
    with pytest.raises(AssertionError):
        check(mutate(TEXT))
