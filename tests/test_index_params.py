"""index/params.py: the shipped params load, and bad params are rejected (#156)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from index.params import IndexParams, Overrides, frac

ROOT = Path(__file__).resolve().parents[1]


def _shipped() -> dict:
    return json.loads((ROOT / "index" / "params.json").read_text())


def test_shipped_params_and_overrides_load() -> None:
    p = IndexParams.model_validate(_shipped())
    o = Overrides.model_validate(json.loads((ROOT / "index" / "overrides.json").read_text()))
    assert p.filters.top10_min_pct == 13 and p.filters.top10_max_pct == 27  # kiwi
    assert p.filters.min_total_fees_sol == 8  # kiwi, D35
    assert (p.membership.size, p.membership.enter_rank, p.membership.exit_rank) == (10, 8, 12)
    assert p.rebalance_hours == 1
    assert p.payout.holder_rewards == "7/10"
    assert p.payout.draw_pot == "3/10" and p.payout.pay_in == "basket"
    assert p.dry_run.skip_filters == ()
    assert o.deny == ()
    f = p.filters
    assert (f.min_age_hours, f.max_bundle_pct) == (4, 30)  # D35
    assert "Lucia" in p.keywords.strong and "VI" not in p.keywords.strong
    assert "Jason" not in p.keywords.strong and len(p.keywords.strong) == 35


def test_removed_rules_are_rejected() -> None:
    for section, key, value in [
        (None, "min_coverage", "1/2"),
        ("filters", "max_dev_pct", 5),
        ("filters", "min_volume_wallets", 30),
        ("keywords", "weak", ["VI"]),
    ]:
        d = _shipped()
        (d[section] if section else d)[key] = value
        with pytest.raises(ValidationError):
            IndexParams.model_validate(d)
    with pytest.raises(ValidationError):
        Overrides.model_validate({"allow": [], "deny": []})


def test_unknown_key_rejected() -> None:
    d = _shipped()
    d["filters"]["surprise"] = 1
    with pytest.raises(ValidationError):
        IndexParams.model_validate(d)


def test_score_weights_must_sum_to_one() -> None:
    d = _shipped()
    d["score"]["w_mc"] = "1/2"
    with pytest.raises(ValidationError):
        IndexParams.model_validate(d)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("membership", "enter_rank", 11),  # enter > size
        ("membership", "exit_rank", 9),  # exit < size
        ("filters", "top10_min_pct", 30),  # min > max
        ("filters", "min_liquidity_usd", 0),  # log of 0 in the score
        ("weights", "cap_pct", 0),
        ("dry_run", "skip_filters", ["F12"]),
    ],
)
def test_inconsistent_values_rejected(section: str, key: str, value: object) -> None:
    d = _shipped()
    d[section][key] = value
    with pytest.raises(ValidationError):
        IndexParams.model_validate(d)


def test_frac_parses_exact_values() -> None:
    assert frac("1/20") * 20 == 1
    assert frac(3) == 3
    with pytest.raises(ValueError):
        frac(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        frac("1/0")
