"""Write web/rules.js from the shipped index and reward parameters.

The public site reads this file so the pages cannot drift from the code.
Run: uv run python tools/gen_web_rules.py
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.index_collect import POOL_MIN_LIQUIDITY_USD  # noqa: E402
from engine.balances import MIN_PAYOUT_Q_MAX  # noqa: E402
from engine.hourly_draw import (  # noqa: E402
    CAP_DEFAULT,
    MIN_GROUPS_DEFAULT,
    MIN_HOLDING_SHARE_DEFAULT,
    MIN_POT_LAMPORTS_DEFAULT,
    SUPPLY_CAP_DEFAULT,
)
from engine.scoring import DEFAULT_HOLD_KNOTS, DEFAULT_T_START_SECONDS  # noqa: E402
from index.params import IndexParams, frac  # noqa: E402

LAMPORTS = 1_000_000_000
# Published holding disclosure (kiwi, 18 Nov). Not a fee parameter and not in params.json.
TEAM_SUPPLY_PCT = 2


def _hours(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    if minutes == 0:
        return f"{h}h"
    return f"{h}h{minutes:02d}"


def _mult(value: Fraction) -> str:
    if value.denominator == 1:
        return f"{int(value)}×"
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return f"{text}×"


def _pct(value: Fraction | int | str) -> str:
    number = float(value if isinstance(value, Fraction) else frac(value)) * 100
    if number == int(number):
        return f"{int(number)}%"
    return f"{number:.1f}%"


def hold_summary(knots: tuple[tuple[int, Fraction], ...], t_start: int) -> str:
    """One sentence for the published knots. Flat after the last knot (D27)."""
    bits: list[str] = []
    i = 0
    while i < len(knots):
        age, height = knots[i]
        j = i
        while j + 1 < len(knots) and knots[j + 1][1] == height:
            j += 1
        if j > i:
            bits.append(f"{_mult(height)} from {_hours(age)} to {_hours(knots[j][0])}")
        else:
            bits.append(f"{_mult(height)} at {_hours(age)}")
        i = j + 1
    body = ", ".join(bits[:-1]) + " and " + bits[-1]
    return (
        f"Nothing before {_hours(t_start)}. The multiplier is {body}, "
        f"then stays at {_mult(knots[-1][1])}."
    )


def build_rules() -> dict:
    params = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
    coin = json.loads((ROOT / "config" / "coin.json").read_text())
    filters = params.filters
    score = params.score
    holder = frac(params.payout.holder_rewards)
    draw = frac(params.payout.draw_pot)
    team = frac(params.payout.team)
    if holder + draw + team != 1:
        raise SystemExit("fee shares do not sum to 1")
    knots = tuple(
        (int(a), h if isinstance(h, Fraction) else Fraction(h)) for a, h in DEFAULT_HOLD_KNOTS
    )
    if int(DEFAULT_T_START_SECONDS) != int(coin["hold"]["t_start_seconds"]):
        raise SystemExit("hold t_start disagrees between scoring.py and coin.json")
    min_pot = int(coin["draws"]["min_pot_lamports"])
    if min_pot != MIN_POT_LAMPORTS_DEFAULT or min_pot != int(params.payout.min_prize_lamports):
        raise SystemExit("draw minimum disagrees between coin.json, hourly_draw and params.json")
    min_pay = int(coin["rewards"]["push_min_transfer_lamports"])
    if min_pay <= 0 or min_pay > MIN_PAYOUT_Q_MAX:
        raise SystemExit("minimum payout is outside the published range")
    fee_line = (
        f"{_pct(team)} of fees go to the team. 100% go to holders: "
        f"{_pct(holder)} is distributed as rewards in the basket coins, "
        f"and {_pct(draw)} goes to the draw pot."
    )
    every = "hour" if int(params.rebalance_hours) == 1 else f"{int(params.rebalance_hours)} hours"
    cap = int(params.weights.cap_pct)
    floor = int(params.weights.floor_pct)
    weight_line = (
        "Weights are proportional to the square root of market cap, "
        f"with an {cap}% cap and a {floor}% floor, recomputed every {every}."
    )
    hold_line = hold_summary(knots, int(DEFAULT_T_START_SECONDS))
    pot_sol = min_pot / LAMPORTS
    pay_sol = min_pay / LAMPORTS
    pay_max = MIN_PAYOUT_Q_MAX / LAMPORTS
    draw_line = (
        "COMING SOON. The draw is not live. When it is turned on it pays SOL prizes from the pot "
        f"and rolls the pot over until it reaches {pot_sol:g} SOL. It also rolls over when fewer "
        f"than {MIN_GROUPS_DEFAULT} eligible holders qualify."
    )
    reward_line = (
        "Rewards accrue with the holding score and are paid once a day. Anything below the "
        f"minimum payout of {pay_sol:g} SOL stays pending, and no token account is opened "
        "for dust. "
        f"That minimum is never set above {pay_max:g} SOL."
    )
    team_line = f"The team holds about {TEAM_SUPPLY_PCT}% of the supply."
    pool_min = int(POOL_MIN_LIQUIDITY_USD)
    liq = int(frac(filters.min_liquidity_usd))
    filter_lines = [
        f"Age at least {int(frac(filters.min_age_hours))} hours",
        (
            f"Liquidity at least ${liq:,}, summed across pools of at least "
            f"${pool_min:,} (smaller pools are ignored)"
        ),
        f"Top 10 holders at most {int(frac(filters.top10_max_pct))}%",
        f"Trading fees at least {int(frac(filters.min_total_fees_sol))} SOL over 24 hours",
        f"Launch bundle at most {int(frac(filters.max_bundle_pct))}%",
        "Mint and freeze authorities revoked",
        f"At least {int(filters.min_unique_traders)} traders in the window",
        "Trading volume greater than 0",
        f"Market cap at most {int(frac(filters.max_mc_liquidity_ratio))}× liquidity",
    ]
    score_line = (
        "Rank uses log S = "
        f"{_pct(score.w_mc)}·ln(market cap) + {_pct(score.w_liquidity)}·ln(liquidity) + "
        f"{_pct(score.w_fees)}·ln(24h fees) + {_pct(score.w_traders)}·ln(traders). "
        "Buy weights are a separate step."
    )
    return {
        "fee_line": fee_line,
        "team_line": team_line,
        "weight_line": weight_line,
        "hold_line": hold_line,
        "reward_line": reward_line,
        "draw_line": draw_line,
        "score_line": score_line,
        "filters": {
            "min_age_hours": int(frac(filters.min_age_hours)),
            "min_liquidity_usd": liq,
            "pool_min_liquidity_usd": pool_min,
            "top10_min_pct": int(frac(filters.top10_min_pct)),
            "top10_max_pct": int(frac(filters.top10_max_pct)),
            "min_fees_sol_24h": int(frac(filters.min_total_fees_sol)),
            "max_bundle_pct": int(frac(filters.max_bundle_pct)),
            "min_unique_traders": int(filters.min_unique_traders),
            "max_mc_liquidity_ratio": int(frac(filters.max_mc_liquidity_ratio)),
            "require_authorities_revoked": bool(filters.require_authorities_revoked),
            "lines": filter_lines,
        },
        "weights": {
            "mode": params.weights.mode,
            "cap_pct": int(params.weights.cap_pct),
            "floor_pct": int(params.weights.floor_pct),
            "rebalance_hours": int(params.rebalance_hours),
        },
        "fees": {
            "team_pct": int(team * 100),
            "holder_pct": int(holder * 100),
            "draw_pct": int(draw * 100),
            "pay_in": params.payout.pay_in,
        },
        "rewards": {
            "period_hours": int(params.payout.holder_reward_hours),
            "min_payout_sol": pay_sol,
            "max_min_payout_sol": pay_max,
            "min_eligible_share": coin["eligibility"]["min_eligible_share"],
        },
        "hold": {
            "t_start_seconds": int(DEFAULT_T_START_SECONDS),
            "max_multiplier": float(knots[-1][1]),
            "flat_after_hours": knots[-1][0] / 3600,
            "knots": [[age / 3600, float(height)] for age, height in knots],
        },
        "draw": {
            "live": bool(coin["draws"]["enabled"]),
            "min_pot_sol": pot_sol,
            "min_groups": MIN_GROUPS_DEFAULT,
            "odds_cap": float(CAP_DEFAULT),
            "supply_cap": float(SUPPLY_CAP_DEFAULT),
            "min_holding_share": float(MIN_HOLDING_SHARE_DEFAULT),
            "period_hours": float(coin["draws"]["period_hours"]),
        },
        "membership": {
            "size": int(params.membership.size),
            "enter_rank": int(params.membership.enter_rank),
            "exit_rank": int(params.membership.exit_rank),
        },
        "checks": [
            (
                "A coin whose market cap is more than 100× its liquidity is blocked "
                "on every hourly run."
            ),
            (
                "Membership does not flip on a one-hour rank wobble: a coin enters at rank 8 "
                "or better and leaves only past rank 12."
            ),
            "A holding younger than 1 hour scores 0.",
            (
                "Draw odds are capped at 5% per holder group, and a pot below the minimum "
                "is not drawn."
            ),
            "Round-trip trades are not removed from volume.",
        ],
    }


def render(rules: dict) -> str:
    payload = json.dumps(rules, indent=2, ensure_ascii=False)
    return (
        "// Generated by tools/gen_web_rules.py from index/params.json and the reward code.\n"
        "// Do not edit by hand. Regenerate with: uv run python tools/gen_web_rules.py\n"
        f"const RULES = {payload};\n"
    )


def main() -> None:
    path = ROOT / "web" / "rules.js"
    path.write_text(render(build_rules()))
    print(path)


if __name__ == "__main__":
    main()
