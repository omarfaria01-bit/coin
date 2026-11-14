"""#85: variants run on the same seeds, never change defaults, and report §14 rows each."""

from __future__ import annotations

import sim.acceptance_v033 as acc
import sim.variants_v033 as var
from engine.params import CoinParams


def test_defaults_untouched_and_variants_differ() -> None:
    assert var.VARIANTS["default"][1] == CoinParams()
    assert CoinParams().hold.t_start_seconds == 7_200
    t_starts = {p.hold.t_start_seconds for _, p in var.VARIANTS.values()}
    assert t_starts == {2 * 3600, 6 * 3600, 12 * 3600, 48 * 3600}


def test_rows_under_restores_params() -> None:
    before = acc.PARAMS
    old_curve = var.VARIANTS["curve old (48h, 2.0× @30d)"][1]
    fails = var.row_failures(old_curve, 1)
    assert acc.PARAMS is before
    assert "Holding time 7d/30d/60d/90d" in fails  # flat after 30d: fails by design
    assert var.row_failures(CoinParams(), 1) == []


def test_short_build_has_every_variant_and_draw_period() -> None:
    text = var.build(seeds=1, days=12, stability=False)
    for name in var.VARIANTS:
        assert f"| {name} |" in text
    for name, _, _ in var.DRAW_VARIANTS:
        assert f"| {name} |" in text
    assert "APR" in text and "no APR or yield" in text  # the only mention is the disclaimer
