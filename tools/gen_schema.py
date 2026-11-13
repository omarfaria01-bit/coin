"""Regenerate config/*.schema.json and config/coin.json defaults from engine/params.py.

Usage: uv run python tools/gen_schema.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.params import CoinParams, PadParams  # noqa: E402

OUTPUTS = {
    ROOT / "config" / "coin.schema.json": CoinParams.model_json_schema(),
    ROOT / "config" / "pad.schema.json": PadParams.model_json_schema(),
}


def render(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, schema in OUTPUTS.items():
        text = render(schema)
        if check:
            if not path.exists() or path.read_text() != text:
                stale.append(path.name)
        else:
            path.write_text(text)
    if stale:
        print(f"stale schema files: {stale}; run: uv run python tools/gen_schema.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
