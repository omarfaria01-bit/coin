"""Emergency removal between rebalances (INDEX_RULES.md §5). Pure: no I/O, no clock."""

from __future__ import annotations

import copy

from index.params import IndexParams
from index.select import mc_volume_of, weights_bps


def apply_emergency(output: dict, mint: str, reason: str, at: str, params: IndexParams) -> dict:
    """Remove `mint` from a published index, recompute weights, log the removal.

    Returns a new dict and never mutates `output`. Removing a coin that is not a member is a
    no-op, so the job can safely re-apply the same removal. No replacement is added until the
    next rebalance.
    """
    if not reason:
        raise ValueError("an emergency removal needs a reason")
    if mint not in {m["mint"] for m in output["members"]}:
        return copy.deepcopy(output)
    out = copy.deepcopy(output)
    out["members"] = [m for m in out["members"] if m["mint"] != mint]
    order = [m["mint"] for m in out["members"]]  # still in rank order
    bps = weights_bps(
        order, {m["mint"]: m["log_s"] for m in out["members"]}, params, mc_volume_of(out["members"])
    )
    for m in out["members"]:
        m["weight_bps"] = bps[m["mint"]]
    out["emergency"] = [*out.get("emergency", []), {"at": at, "mint": mint, "reason": reason}]
    return out
