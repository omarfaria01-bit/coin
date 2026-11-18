"""COIN_MATH.md defaults vs ``engine/params.py`` (issue #151).

COIN_MATH.md is prose, so the mapping between its published defaults and the typed
parameters is explicit here. CI fails when a value drifts:

* ``SPEC_DEFAULTS`` - documented defaults that match ``CoinParams()`` today.
* ``KNOWN_DRIFT``  - documented defaults that do not match yet. Each row pins today's
                     value *and* the value COIN_MATH states, and is tracked in issue
                     #152. Fixing one turns the strict xfail into an XPASS, so the row
                     must move to ``SPEC_DEFAULTS`` in the same PR.
* ``OUTSIDE_PARAMS`` - documented defaults that live in another engine module instead
                     of ``params.py``. Their current value is pinned to COIN_MATH.
* ``UNDOCUMENTED`` - params fields with no COIN_MATH default (legacy v0.2 or
                     provisional), each with a reason. Every leaf of ``CoinParams``
                     must be in exactly one bucket, so a new field cannot slip in
                     silently.

Changing any default needs a DECISIONS.md entry and a sim re-run (CLAUDE.md); it is
never a silent edit to this file alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from importlib import import_module
from pathlib import Path

import pytest
from pydantic import BaseModel

from engine.params import CoinParams

ROOT = Path(__file__).resolve().parent.parent
COIN_MATH = ROOT / "COIN_MATH.md"
TRACKING_ISSUE = 152

_HOUR = 3_600
_DAY = 86_400


# --------------------------------------------------------------------------- tables


@dataclass(frozen=True, slots=True)
class SpecDefault:
    section: str
    name: str
    path: str
    value: object


@dataclass(frozen=True, slots=True)
class Drift:
    section: str
    name: str
    spec_says: str
    # path -> (COIN_MATH default, params.py today)
    values: Mapping[str, tuple[object, object]]


@dataclass(frozen=True, slots=True)
class OutsideParams:
    section: str
    name: str
    location: str
    value: object


_HOLD_KNOTS = (
    (1 * _HOUR, Fraction(1)),
    (90 * 60, Fraction(1)),
    (105 * 60, Fraction(3, 2)),
    (2 * _HOUR, Fraction(2)),
    (150 * 60, Fraction(3)),
    (3 * _HOUR, Fraction(4)),
    (4 * _HOUR, Fraction(5)),
)

SPEC_DEFAULTS: tuple[SpecDefault, ...] = (
    SpecDefault("0", "E = 86,400 s epoch", "epoch.hours", 24),
    SpecDefault(
        "2",
        "MIN_ELIGIBLE_SHARE = 1/1,000,000",
        "eligibility.min_eligible_share",
        Fraction(1, 10**6),
    ),
    SpecDefault("3", "T_START = 1 hour", "hold.t_start_seconds", 1 * _HOUR),
    SpecDefault("3", "h(a) knot table", "hold.knots", _HOLD_KNOTS),
    SpecDefault("3", "E1/E2 split at 48h", "hold.boost_age_seconds", 48 * _HOUR),
    SpecDefault("5", "P-bar window = the epoch's 86,400 s", "underwater.twap_hours", 24),
    SpecDefault("5", "beta = 1/2", "underwater.beta", Fraction(1, 2)),
    SpecDefault("5", "D_max = 3/4", "underwater.d_max", Fraction(3, 4)),
    SpecDefault("5", "boost starts at age 48h", "underwater.min_age_hours", 48),
    SpecDefault("16", "underwater boost off at launch", "underwater.enabled", False),
    SpecDefault("6", "CAP = 1/20", "scoring.cap", Fraction(1, 20)),
    SpecDefault("7", "links merge at sum >= 1", "sybil.merge_threshold", 1),
    SpecDefault("7", "shared fee payer has no link weight", "sybil.weights.same_fee_payer", 0),
    SpecDefault(
        "7", "L1 token transfer weight 0.6", "sybil.weights.direct_transfer", Fraction(3, 5)
    ),
    SpecDefault("7", "L4 co-trade weight 0.4", "sybil.weights.co_buy", Fraction(2, 5)),
    SpecDefault(
        "7", "L5 identical balance weight 0.3", "sybil.weights.identical_balances", Fraction(3, 10)
    ),
    SpecDefault("7", "review clusters > 50 wallets", "sybil.review_cluster_size", 50),
    SpecDefault("7", "L4 same-second tolerance +/-1", "sybil.co_buy_slot_tolerance", 1),
    SpecDefault("7", "L4 size tolerance 10%", "sybil.co_buy_size_tolerance", Fraction(1, 10)),
    SpecDefault("7", "L4 min occurrences 3", "sybil.co_buy_min_occurrences", 3),
    SpecDefault(
        "7", "L5 balance tolerance 0.1%", "sybil.identical_balance_tolerance", Fraction(1, 1000)
    ),
    SpecDefault("7", "L5 min wallets 4", "sybil.identical_balance_min_wallets", 4),
    SpecDefault("7", "L5 created within 24h", "sybil.identical_balance_created_within_hours", 24),
    SpecDefault("8", "alpha = 1/10 per day", "rewards.alpha_per_day", Fraction(1, 10)),
    SpecDefault("8", "lst_share = 0 at launch", "rewards.lst_fraction", 0),
    SpecDefault("13", "push below 500 eligible", "rewards.push_max_eligible", 500),
    SpecDefault(
        "13", "MIN_PAYOUT_Q default 0.001 SOL", "rewards.push_min_transfer_lamports", 1_000_000
    ),
    SpecDefault("16", "holder rewards on at launch", "rewards.enabled", True),
    SpecDefault("9", "draw eligibility has no USD gate", "draws.min_balance_usd", 0),
    SpecDefault("9", "DRAW_PERIOD = 1 hour", "draws.period_hours", 1),
    SpecDefault("9", "cap 5% of the odds", "draws.cap", Fraction(1, 20)),
    SpecDefault("9", "minimum pot 0.01 SOL", "draws.min_pot_lamports", 10_000_000),
    SpecDefault("9", "eligible after a 1h hold", "draws.min_hold_hours", 1),
    SpecDefault(
        "9",
        "prizes 1x40% + 3x10% + 6x5%",
        "draws.prize_split",
        (0.40, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05),
    ),
    SpecDefault("16", "draws off at launch", "draws.enabled", False),
    SpecDefault("10", "dev 0%", "fees.dev", Fraction(0)),
    SpecDefault("10", "holder pot 70%", "fees.holder_pot", Fraction(7, 10)),
    SpecDefault("10", "draw pot 30%", "fees.draw_pot", Fraction(3, 10)),
    SpecDefault("10", "buyback & burn 0%", "fees.buyback_burn", Fraction(0)),
    SpecDefault("10", "router every 60 min", "fees.router_interval_minutes", 60),
    SpecDefault("11", "T_EARLY = 15 min", "vesting.t_early_minutes", 15),
    SpecDefault("11", "MC_EARLY unset = time only", "vesting.mc_early_usd", None),
    SpecDefault("11", "T_v = 7 days", "vesting.t_v_days", 7),
    SpecDefault("11", "M = 5", "vesting.m", 5),
    SpecDefault("11", "UNLOCK_TWAP_H = 24h", "vesting.unlock_twap_hours", 24),
    SpecDefault("11", "soft forfeit = 30 days", "vesting.forfeit_days", 30),
    SpecDefault("0", "D_TRUST default 2 SOL", "prices.d_trust_lamports", 2_000_000_000),
    SpecDefault("16", "treasury bot off at launch", "treasury_bot.enabled", False),
    SpecDefault("12", "mode = paper", "treasury_bot.mode", "paper"),
    SpecDefault("12", "EMA half-life 6h", "treasury_bot.ema_halflife_hours", 6),
    SpecDefault("12", "variance half-life 24h", "treasury_bot.var_halflife_hours", 24),
    SpecDefault("12", "f0 = 0.5", "treasury_bot.f0", 0.5),
    SpecDefault("12", "gamma = 0.15", "treasury_bot.gamma", 0.15),
    SpecDefault("12", "f_min = 0.1", "treasury_bot.f_min", 0.1),
    SpecDefault("12", "f_max = 0.9", "treasury_bot.f_max", 0.9),
    SpecDefault("12", "band = 0.05", "treasury_bot.band", 0.05),
    SpecDefault("12", "max 2% of 1h pool volume", "treasury_bot.max_pool_volume_fraction", 0.02),
    SpecDefault("12", "no trades in the first 24h", "treasury_bot.no_trade_first_hours", 24),
    SpecDefault(
        "12",
        "falling knife at -40% from the 72h high",
        "treasury_bot.breaker_drawdown",
        Fraction(2, 5),
    ),  # fmt: skip
    SpecDefault("12", "weekly profit sweep 50%", "treasury_bot.sweep_fraction", 0.5),
)

# Empty since #152 aligned all eight rows with COIN_MATH. Kept so a future drift can be
# pinned here instead of turning CI red on the day it is found.
KNOWN_DRIFT: tuple[Drift, ...] = ()

OUTSIDE_PARAMS: tuple[OutsideParams, ...] = (
    OutsideParams("6", "G = 2 uplift limit", "engine.rewards.DEFAULT_G", 2),
    OutsideParams(
        "9",
        "MIN_DRAW_SHARE = 1/100,000",
        "engine.draws.MIN_DRAW_SHARE_DEFAULT",
        Fraction(1, 100_000),
    ),
    OutsideParams("9", "delta = 1 weekly draw", "engine.draws.DELTA_DEFAULT", 1),
    OutsideParams(
        "13",
        "unclaimed re-credited after 30 days",
        "engine.balances.UNCLAIMED_RECREDIT_SECONDS",
        30 * _DAY,
    ),
    OutsideParams(
        "13",
        "unclaimed back to pot after 180 days",
        "engine.balances.UNCLAIMED_TO_POT_SECONDS",
        180 * _DAY,
    ),
    OutsideParams(
        "7",
        "hub candidate at 25 counterparties",
        "engine.sybil_v033.HUB_CANDIDATE_COUNTERPARTIES",
        25,
    ),
    OutsideParams("7", "fee payer shared by 5 holders", "engine.sybil_v033.REVIEW_SHARED_PAYER", 5),
)

# Params fields with no COIN_MATH default. Reasons are quotes/section pointers, so the
# allowlist stays auditable: a field leaves this dict when #152 decides its home.
UNDOCUMENTED: Mapping[str, str] = {
    "version": "config schema version, not a COIN_MATH parameter (doc is v0.3.3)",
    "hold.horizon_days": "v0.2 h(a) horizon; replaced by hold.knots, unused",
    "churn.window_hours": "v0.2 flipper discount; §4 removed churn in v0.3.3, unused",
    "churn.kappa": "v0.2 flipper discount; §4 removed churn in v0.3.3, unused",
    "sybil.weights.same_first_funder": "v0.2 weight set; S2 is a strong edge, not a weight",
    "sybil.strong_edge": "v0.2 numeric threshold; §7 treats strong evidence categorically",
    "sybil.funder_window_hours": "v0.2 funding window; §7 S2 uses lifetime totals",
    "rewards.min_epoch_payout_lamports": (
        "PROVISIONAL: §8 names MIN_EPOCH_PAYOUT but gives no number"
    ),
    "treasury_bot.seed_lamports": "BOT_CAPITAL_Q is set by kiwi at funding; no default",
    "treasury_bot.max_trade_lamports": "MAX_TRADE_Q is set at funding; no default",
    "treasury_bot.min_liquidity_lamports": "L_MIN is set at funding; no numeric default",
    "treasury_bot.daily_loss_limit_lamports": "§12 rule is 5% of capital, not an absolute default",
    "treasury_bot.quiet_minutes": "BOT_QUIET_MIN is not in §12",
}


# -------------------------------------------------------------------------- helpers


def _norm(value: object) -> object:
    """Compare exactly: floats go through their decimal text so 0.1 == Fraction(1, 10)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return Fraction(value)
        except ValueError:
            return value
    if isinstance(value, tuple):
        return tuple(_norm(item) for item in value)
    if isinstance(value, list):
        return [_norm(item) for item in value]
    if isinstance(value, int | Fraction):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    return value


def _resolve(obj: object, path: str) -> object:
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _module_constant(location: str) -> object:
    module_name, _, attr = location.rpartition(".")
    return getattr(import_module(module_name), attr)


def _coin_leaf_paths(model: type[BaseModel] = CoinParams, prefix: str = "") -> list[str]:
    paths: list[str] = []
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths += _coin_leaf_paths(annotation, f"{path}.")
        else:
            paths.append(path)
    return paths


# ---------------------------------------------------------------------------- tests


@pytest.mark.parametrize("entry", SPEC_DEFAULTS, ids=lambda e: e.path)
def test_documented_default_matches_params(entry: SpecDefault) -> None:
    actual = _resolve(CoinParams(), entry.path)
    assert _norm(actual) == _norm(entry.value), (
        f"COIN_MATH §{entry.section} {entry.name}: params {entry.path}={actual!r}, "
        f"spec {entry.value!r}. Changing a default needs DECISIONS.md + a sim re-run."
    )


@pytest.mark.parametrize("entry", KNOWN_DRIFT, ids=lambda e: e.name)
def test_known_drift_pins_todays_params(entry: Drift) -> None:
    """Any change to a drifted value turns CI red instead of hiding in the xfail."""
    params = CoinParams()
    for path, (_spec, today) in entry.values.items():
        actual = _resolve(params, path)
        assert _norm(actual) == _norm(today), (
            f"{path} is {actual!r}, pinned to {today!r}. Update KNOWN_DRIFT and issue "
            f"#{TRACKING_ISSUE} together."
        )


@pytest.mark.xfail(strict=True, reason=f"COIN_MATH vs params drift, tracked in #{TRACKING_ISSUE}")
@pytest.mark.parametrize("entry", KNOWN_DRIFT, ids=lambda e: e.name)
def test_known_drift_entry_matches_spec(entry: Drift) -> None:
    params = CoinParams()
    for path, (spec, _today) in entry.values.items():
        actual = _resolve(params, path)
        assert _norm(actual) == _norm(spec), (
            f"§{entry.section} {entry.name}: {path}={actual!r}, spec expects {spec!r} "
            f"({entry.spec_says}). Move the row to SPEC_DEFAULTS and close #{TRACKING_ISSUE}."
        )


@pytest.mark.parametrize("entry", OUTSIDE_PARAMS, ids=lambda e: e.name)
def test_documented_default_lives_outside_params(entry: OutsideParams) -> None:
    actual = _module_constant(entry.location)
    assert _norm(actual) == _norm(entry.value), (
        f"COIN_MATH §{entry.section} {entry.name}: {entry.location}={actual!r}, "
        f"spec {entry.value!r}"
    )


def test_every_params_field_is_classified() -> None:
    leaves = _coin_leaf_paths()
    assert len(leaves) == len(set(leaves)), "duplicate leaf path"

    spec = [entry.path for entry in SPEC_DEFAULTS]
    drift = [path for entry in KNOWN_DRIFT for path in entry.values]
    assert len(spec) == len(set(spec)), "duplicate SPEC_DEFAULTS path"
    assert len(drift) == len(set(drift)), "duplicate KNOWN_DRIFT path"

    buckets = (set(spec), set(drift), set(UNDOCUMENTED))
    assert not buckets[0] & buckets[1] and not buckets[0] & buckets[2]
    assert not buckets[1] & buckets[2], "a path is in two buckets"

    documented = set().union(*buckets)
    assert set(leaves) - documented == set(), (
        "new params field(s) with no COIN_MATH mapping: "
        f"{sorted(set(leaves) - documented)}; add them to SPEC_DEFAULTS, KNOWN_DRIFT or "
        "UNDOCUMENTED with a reason"
    )
    assert documented - set(leaves) == set(), (
        f"table row(s) for a missing/renamed field: {sorted(documented - set(leaves))}"
    )


def test_duplicated_engine_defaults_agree_with_params() -> None:
    params = CoinParams()
    assert _norm(_module_constant("engine.rewards.DEFAULT_CAP")) == _norm(params.scoring.cap)
    assert _norm(_module_constant("engine.balances.MIN_PAYOUT_Q_DEFAULT")) == _norm(
        params.rewards.push_min_transfer_lamports
    )


def test_referenced_coin_math_sections_exist() -> None:
    text = COIN_MATH.read_text(encoding="utf-8")
    sections = {entry.section for entry in SPEC_DEFAULTS}
    sections |= {entry.section for entry in KNOWN_DRIFT}
    sections |= {entry.section for entry in OUTSIDE_PARAMS}
    missing = sorted(section for section in sections if f"## {section}." not in text)
    assert not missing, f"COIN_MATH.md has no heading for section(s) {missing}; update the mapping"
