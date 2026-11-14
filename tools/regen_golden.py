"""Regenerate the v0.3.3 golden epoch replay (#83). The ONLY way to update the goldens.

    uv run python tools/regen_golden.py           # rewrite tests/golden/v033/
    uv run python tools/regen_golden.py --check   # exit 1 if the goldens are stale

Runs `tests/golden/v033_replay.json` (3 epochs: S2 cluster, soft-vesting forfeit, tainted lot
sold to the pool, price unlock from trusted reserves, sniper < T_START, pending carry then paid)
through tools/run_epoch with the committed config/coin.json. Any change to engine math or to a
default changes these bytes; review the diff, then commit it with the change that caused it.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_epoch import run  # noqa: E402

FIXTURE = ROOT / "tests" / "golden" / "v033_replay.json"
GOLDEN = ROOT / "tests" / "golden" / "v033"


def render(out: Path) -> dict[str, bytes]:
    """Run the fixture into `out`; return {relative path: bytes} for every written file."""
    run(FIXTURE, out)
    return {
        p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()
    }


def digest(files: dict[str, bytes]) -> str:
    """One SHA-256 over every (path, bytes) pair, in path order."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + files[name] + b"\0")
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare only; exit 1 on any diff")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        fresh = render(Path(tmp))
        if args.check:
            current = {
                p.relative_to(GOLDEN).as_posix(): p.read_bytes()
                for p in sorted(GOLDEN.rglob("*"))
                if p.is_file()
            }
            stale = sorted(
                k for k in fresh.keys() | current.keys() if fresh.get(k) != current.get(k)
            )
            for name in stale:
                print(f"stale: tests/golden/v033/{name}", file=sys.stderr)
            return 1 if stale else 0
        # Write a sibling dir first and swap it in, so a crash never leaves half a golden set.
        staged = GOLDEN.with_name(GOLDEN.name + ".new")
        shutil.rmtree(staged, ignore_errors=True)
        for name, blob in fresh.items():
            dest = staged / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
        shutil.rmtree(GOLDEN, ignore_errors=True)
        staged.rename(GOLDEN)
    print(f"wrote {len(fresh)} files under {GOLDEN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
