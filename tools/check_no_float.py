"""No-float ratchet for the payout path (COIN_MATH v0.3.3 §0 "Numbers").

The payout path may use only ints and ``fractions.Fraction``: no ``math`` import, no
float literal, no ``float`` name. BASELINE is empty and must stay empty: #84 deleted
the v0.2 float code, so there is no grandfathered code left.

- any violation fails (new float code);
- a stale BASELINE entry fails too (it may only ever be empty).

Usage: uv run python tools/check_no_float.py
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = (
    "events", "prices", "ledger", "twab", "sybil", "scoring",
    "rewards", "draws", "vesting", "merkle", "balances", "sybil_v033",
)  # fmt: skip

# (module, top-level def/class or "<module>") → still allowed; must stay empty.
BASELINE: frozenset[tuple[str, str]] = frozenset()


def violations(source: str) -> dict[str, list[str]]:
    """Top-level name → sorted list of 'line N: what' for each float use."""
    found: dict[str, list[str]] = {}

    def owner_of(stmt: ast.stmt) -> str:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return stmt.name
        return "<module>"

    for stmt in ast.parse(source).body:
        owner = owner_of(stmt)
        for node in ast.walk(stmt):
            what = None
            if isinstance(node, ast.Import) and any(a.name == "math" for a in node.names):
                what = "import math"
            elif isinstance(node, ast.ImportFrom) and node.module == "math":
                what = "from math import"
            elif isinstance(node, ast.Constant) and type(node.value) is float:
                what = f"float literal {node.value!r}"
            elif isinstance(node, ast.Name) and node.id == "float":
                what = "float"
            if what:
                found.setdefault(owner, []).append(f"line {node.lineno}: {what}")
    return {k: sorted(v) for k, v in found.items()}


def check(root: Path = ROOT, baseline: frozenset[tuple[str, str]] = BASELINE) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for mod in MODULES:
        path = root / "engine" / f"{mod}.py"
        if not path.exists():
            continue
        for owner, hits in violations(path.read_text()).items():
            seen.add((mod, owner))
            if (mod, owner) not in baseline:
                errors.extend(f"engine/{mod}.py {owner} {hit}" for hit in hits)
    for mod, owner in sorted(baseline - seen):
        if (root / "engine" / f"{mod}.py").exists():
            errors.append(f"stale BASELINE entry ({mod!r}, {owner!r}): now float-free, delete it")
    return errors


def main() -> int:
    errors = check()
    for err in errors:
        print(err)
    if errors:
        print(f"{len(errors)} no-float violation(s); see COIN_MATH §0 Numbers")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
