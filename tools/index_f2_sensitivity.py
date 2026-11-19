"""#251: F2 (liquidity floor) sensitivity, replayed offline from saved index inputs.

Read-only: no network, no keys. Reads `data/index/inputs/<ts>.json` files written by
tools/run_index.py (the exact `inputs_hash` preimage), checks each against its recorded hash,
then re-runs the pure `index.select.run_index` with only `filters.min_liquidity_usd` changed.
Nothing else (params, INDEX_RULES, published outputs) is touched: the F2 value is kiwi's call.

Usage:
  uv run python tools/index_f2_sensitivity.py data/index/inputs [--last 1] \
      [--params index/params.json] [--thresholds 5000,10000,25000,50000] > report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from index.params import IndexParams, Overrides, frac  # noqa: E402
from index.select import canonical_json, metrics_from_json, run_index, sha256_hex  # noqa: E402

DEFAULT_THRESHOLDS = (5_000, 10_000, 25_000, 50_000)
PRESCREEN_TAG = "skipped: dexscreener liquidity below prescreen"


def load_inputs(path: Path) -> dict:
    """Load one saved inputs file and verify it hashes to its recorded inputs_hash."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    pre = {k: doc[k] for k in ("candidates", "prev_members", "overrides")}
    got = sha256_hex(canonical_json(pre))
    if got != doc.get("inputs_hash"):
        raise ValueError(f"{path.name}: inputs_hash mismatch ({got} != {doc.get('inputs_hash')})")
    return doc


def sensitivity(doc: dict, params: IndexParams, thresholds: Sequence[int]) -> list[dict]:
    """One row per threshold: members, top-N tickers with weight_bps, F2 exclusions."""
    candidates = [metrics_from_json(c) for c in doc["candidates"]]
    overrides = Overrides.model_validate(doc["overrides"])
    prescreen = float(
        frac(params.filters.min_liquidity_usd) * frac(params.discovery.prescreen_liquidity_share)
    )
    rows = []
    for t in thresholds:
        p = params.model_copy(
            update={"filters": params.filters.model_copy(update={"min_liquidity_usd": t})}
        )
        out = run_index(
            candidates, doc["prev_members"], p, overrides, doc["as_of"], "f2-sensitivity"
        )
        members = [(m["ticker"], m["weight_bps"]) for m in out["members"]]
        reasons = [e["reason"] for e in out["excluded"]]
        rows.append(
            {
                "threshold": t,
                "members": len(members),
                "top": members,
                "bps_sum": sum(b for _, b in members),
                "f2_excluded": reasons.count("F2"),
                # never measured: below the DexScreener prescreen of the run that saved the file
                "not_measured": sum(
                    1
                    for e in out["excluded"]
                    if any(PRESCREEN_TAG in str(x) for x in e.get("missing") or [])
                ),
                "below_prescreen": t < prescreen,
            }
        )
    return rows


def render(doc: dict, rows: list[dict]) -> str:
    lines = [
        f"### as_of {doc['as_of']} (inputs_hash `{doc['inputs_hash'][:12]}…`, "
        f"{len(doc['candidates'])} candidates)",
        "",
        "| F2 floor (USD) | members | top-10 (ticker bps) | bps sum | F2 excluded | not measured |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for r in rows:
        top = ", ".join(f"{t} {b}" for t, b in r["top"]) or "-"
        flag = " ⚠" if r["below_prescreen"] else ""
        lines.append(
            f"| {r['threshold']:,}{flag} | {r['members']} | {top} | {r['bps_sum']} | "
            f"{r['f2_excluded']} | {r['not_measured']} |"
        )
    if any(r["below_prescreen"] for r in rows):
        lines += [
            "",
            "⚠ below the prescreen of the saved run: coins under it were never measured, so this "
            "row is a lower bound (they are counted in *not measured*, not guessed).",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", type=Path, help="an inputs .json file or a directory of them")
    ap.add_argument("--last", type=int, default=1, help="newest N files of a directory")
    ap.add_argument("--params", type=Path, default=ROOT / "index" / "params.json")
    ap.add_argument("--thresholds", default=",".join(str(t) for t in DEFAULT_THRESHOLDS))
    a = ap.parse_args(argv)
    params = IndexParams.model_validate(json.loads(a.params.read_text(encoding="utf-8")))
    thresholds = [int(x) for x in a.thresholds.split(",") if x.strip()]
    if a.inputs.is_dir():
        files = sorted(a.inputs.glob("*.json"))[-a.last :]
    else:
        files = [a.inputs] if a.inputs.is_file() else []
    if not files:
        print(f"no inputs files in {a.inputs}", file=sys.stderr)
        return 2
    print("# F2 liquidity floor sensitivity (#251) — report only, no default changed\n")
    for f in files:
        doc = load_inputs(f)
        print(render(doc, sensitivity(doc, params, thresholds)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
