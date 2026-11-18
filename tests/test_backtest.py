"""Backtest math and the public rules file stay on the shipped parameters."""

from __future__ import annotations

import json
from pathlib import Path

from index.filters import Metrics, first_failed_filter
from index.params import IndexParams, Overrides
from sim.backtest import (
    CoinPath,
    load_official,
    max_drawdown,
    passing_members,
    portfolio_return,
    simulate,
    weight_from_mc,
)
from tools.gen_web_rules import build_rules, render

ROOT = Path(__file__).resolve().parents[1]


def _params() -> IndexParams:
    return IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))


def _coin(i: int, mc: float, age: float = 30.0) -> Metrics:
    return Metrics(
        mint=f"mint{i}",
        ticker=f"GTA{i}",
        name="GTA 6 coin",
        coverage=1.0,
        age_hours=age,
        liquidity_usd=max(mc / 10, 100_000.0),
        mc_usd=mc,
        top10_pct=20.0,
        total_fees_sol=40.0,
        trading_fees_24h_sol=40.0,
        window_fees_sol=12.0,
        bundle_pct=2.0,
        dev_pct=1.0,
        creator_launches_7d=1,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        extensions=(),
        unique_traders=500,
        independent_traders=500,
        volume_usd=mc,
    )


def test_max_drawdown_peak_to_trough() -> None:
    assert max_drawdown([1.0, 1.5, 0.75]) == 0.5
    assert max_drawdown([1.0, 1.2, 1.3]) == 0.0
    assert max_drawdown([]) == 0.0


def test_weights_sum_and_respect_cap_floor() -> None:
    params = _params()
    pairs = [(f"m{i}", float(i + 1) ** 2 * 1_000_000) for i in range(8)]
    bps = weight_from_mc(pairs, params)
    assert sum(bps.values()) == 10_000
    # 8 coins: 18% cap and 5% floor are both feasible.
    assert all(500 <= v <= 1800 for v in bps.values())
    ordered = sorted(pairs, key=lambda pair: pair[1])
    assert bps[ordered[0][0]] <= bps[ordered[-1][0]]


def test_few_coins_are_equal_when_cap_cannot_bind() -> None:
    params = _params()
    bps = weight_from_mc([("a", 100.0), ("b", 25.0), ("c", 4.0)], params)
    assert sum(bps.values()) == 10_000
    assert max(bps.values()) - min(bps.values()) <= 1


def test_portfolio_return_uses_weights() -> None:
    got = portfolio_return({"a": 7500, "b": 2500}, {"a": 0.10, "b": -0.10})
    assert abs(got - 0.05) < 1e-12


def test_young_coin_is_dropped_by_current_filters() -> None:
    params = _params()
    young = _coin(1, 1_000_000.0, age=1.0)
    assert first_failed_filter(young, params) == "F1"
    doc = {
        "members": [
            {"mint": young.mint, "ticker": young.ticker, "metrics": young.__dict__},
            {"mint": "mint2", "ticker": "GTA2", "metrics": _coin(2, 2_000_000.0).__dict__},
        ]
    }
    kept = passing_members(doc, params, Overrides())
    assert [m.mint for m in kept] == ["mint2"]


def test_simulate_doubling_is_two_and_rebalances_each_hour() -> None:
    params = _params()
    bars = {i * 3600: (1.0 + i, 10.0) for i in range(4)}  # prices 1,2,3,4
    # Identical paths so weights are equal and the index matches the coin.
    coins = [
        CoinPath(
            f"m{k}", f"GTA{k}", pool_created=0, anchor_mc=1_000_000.0, anchor_px=1.0, bars=bars
        )
        for k in range(6)
    ]
    sol = {i * 3600: 100.0 for i in range(4)}
    out = simulate(coins, params, sol, min_age_hours=4)
    # First hour is before the 4h age, so the book starts at hour 4*3600...
    # pool_created=0 and min age 4h means hour 0,1,2,3*3600: hour 0 is not old enough
    # hours are 0, 3600, 7200, 10800. Age cut is 14400, so NONE of these hours pass.
    assert out["history"]["rebalances"] == 0

    bars2 = {(10 + i) * 3600: (float(2**i), 5.0) for i in range(3)}
    coins2 = [CoinPath("m0", "GTA0", pool_created=0, anchor_mc=8.0, anchor_px=4.0, bars=bars2)]
    out2 = simulate(coins2, params, None, min_age_hours=4)
    # prices 1, 2, 4 at hours 10,11,12. Two steps of +100%. End = 4.
    assert out2["history"]["rebalances"] == 2
    assert out2["index"]["end"] == 4.0
    assert out2["equal_weight"]["end"] == 4.0
    assert out2["coins"][0]["hours"] == 2


def test_gap_does_not_invent_a_two_hour_return() -> None:
    params = _params()
    bars = {10 * 3600: (10.0, 1.0), 12 * 3600: (20.0, 1.0)}
    coin = CoinPath("m0", "GTA0", 0, 10.0, 10.0, bars)
    out = simulate([coin], params, None, min_age_hours=0)
    assert out["history"]["rebalances"] == 0
    assert out["index"]["end"] == 1.0


def test_dry_run_files_are_ignored(tmp_path: Path) -> None:
    early = {"as_of": "a", "dry_run": True, "members": [1]}
    (tmp_path / "2026-11-18T01.json").write_text(json.dumps(early))
    (tmp_path / "2026-11-18T02.dryrun.json").write_text("{}")
    (tmp_path / "emergency.json").write_text("{}")
    later = {"as_of": "b", "dry_run": False, "members": []}
    (tmp_path / "2026-11-18T03.json").write_text(json.dumps(later))
    docs = load_official(tmp_path)
    assert [d["as_of"] for d in docs] == ["b"]


def test_rules_match_params_and_hold_curve() -> None:
    rules = build_rules()
    params = _params()
    assert rules["filters"]["min_age_hours"] == 4
    assert rules["filters"]["min_liquidity_usd"] == 50_000
    assert rules["filters"]["pool_min_liquidity_usd"] == 10_000
    assert rules["filters"]["top10_max_pct"] == 30
    assert rules["filters"]["top10_min_pct"] == 0
    assert rules["filters"]["min_fees_sol_24h"] == 8
    assert rules["filters"]["min_unique_traders"] == int(params.filters.min_unique_traders) == 50
    assert rules["filters"]["max_bundle_pct"] == 30
    assert rules["weights"]["cap_pct"] == 18
    assert rules["weights"]["floor_pct"] == 5
    assert rules["weights"]["mode"] == "sqrt_mc_capped"
    assert rules["fees"]["team_pct"] == 0
    assert rules["fees"]["holder_pct"] == 70
    assert rules["fees"]["draw_pct"] == 30
    assert rules["hold"]["max_multiplier"] == 10
    assert rules["hold"]["chart_max"] == 5
    assert rules["hold"]["log_cap_hours"] == 720
    assert rules["hold"]["t_start_seconds"] == 3600
    assert rules["draw"]["live"] is False
    assert rules["draw"]["min_pot_sol"] == 0.1
    assert rules["rewards"]["min_payout_lamports"] == 1_513_840
    assert "10× at 30 days" in rules["hold_line"]
    assert "stays at 5×" not in rules["hold_line"]
    assert "one SOL prize" in rules["draw_line"]
    assert "0.1 SOL" in rules["draw_line"]
    text = (ROOT / "web" / "rules.js").read_text()
    assert text == render(rules)


def test_site_copy_has_no_forbidden_phrases() -> None:
    blob = []
    for path in (ROOT / "web").rglob("*"):
        if path.suffix.lower() not in {".html", ".js", ".css", ".md"}:
            continue
        blob.append(path.read_text(encoding="utf-8"))
    text = "\n".join(blob)
    lowered = text.lower()
    for phrase in (
        "apr",
        "apy",
        "yield",
        "guaranteed returns",
        "no buyback",
        "no team share",
        "zero team tokens",
    ):
        assert phrase not in lowered
    rules = build_rules()
    html = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "web").glob("*.html"))
    js = (ROOT / "web" / "rules.js").read_text(encoding="utf-8")
    for key in ("fee_line", "team_line", "weight_line", "hold_line", "reward_line", "draw_line"):
        assert rules[key] in js
        assert rules[key] in html
    assert "COMING SOON" in text
    assert "not affiliated with Rockstar Games" in text
