"""D39 sybil-split simulation (audit #271 C1): old isqrt odds vs D39 linear odds. Exact, no I/O.

Population: 300 honest groups at 0.25% of supply each (75%); an attacker holds a fixed amount
and splits it over N unlinked wallets (CEX-funded, so §7 cannot link them). Score = balance × 5
(everyone past the 4h knot). Odds are exact Fractions from the engine's weights.

    uv run python -m sim.rewards_d39_sybil   # prints reports/rewards_d39_sybil_2026-11.md
"""

from __future__ import annotations

from fractions import Fraction

from engine.draws import draw_weight
from engine.hourly_draw import (
    CAP_DEFAULT,
    MIN_HOLDING_SHARE_DEFAULT,
    cap_weights,
    draw_weights,
)

SUPPLY = 10**15  # 1B tokens × 10^6 base units
MULT = 5
HONEST = {f"h{i:03d}": SUPPLY // 400 for i in range(300)}  # 0.25% each
SPLITS = (1, 10, 100, 1000)


def population(attacker_balance: int, n: int) -> dict[str, int]:
    """Balances: honest groups plus the attacker's amount split into n equal wallets."""
    part, rest = divmod(attacker_balance, n)
    pieces = {f"a{i:04d}": part + (1 if i < rest else 0) for i in range(n)}
    return HONEST | pieces


def share_d39(bal: dict[str, int], min_holding: Fraction = MIN_HOLDING_SHARE_DEFAULT) -> Fraction:
    scores = {c: b * MULT for c, b in bal.items()}
    w = draw_weights(scores, bal, SUPPLY, min_holding_share=min_holding)
    return Fraction(sum(v for c, v in w.items() if c.startswith("a")), sum(w.values()))


def share_sqrt_d28(bal: dict[str, int]) -> Fraction:
    """The pre-D39 rule: isqrt(score), 5% odds cap, no supply cap, no minimum holding."""
    w = cap_weights({c: draw_weight(b * MULT) for c, b in bal.items()}, CAP_DEFAULT)
    return Fraction(sum(v for c, v in w.items() if c.startswith("a")), sum(w.values()))


def proportional(attacker_balance: int) -> Fraction:
    return Fraction(attacker_balance, attacker_balance + sum(HONEST.values()))


def table(attacker_pct: Fraction) -> list[tuple[int, Fraction, Fraction, Fraction]]:
    amount = int(attacker_pct * SUPPLY)
    rows = []
    for n in SPLITS:
        bal = population(amount, n)
        rows.append((n, share_sqrt_d28(bal), share_d39(bal), share_d39(bal, Fraction(1, 10**9))))
    return rows


def _pct(x: Fraction) -> str:
    return f"{float(x) * 100:.4f}%"


def render_report() -> str:
    small = table(Fraction(3, 100))
    whale = table(Fraction(20, 100))

    def rows(t):
        return "\n".join(f"| {n:,} | {_pct(a)} | {_pct(b)} | {_pct(c)} |" for n, a, b, c in t)

    return f"""# D39 sybil split: old sqrt odds vs linear odds (18 Nov 2026)

Audit #271 C1, decision D39. Model `sim/rewards_d39_sybil.py` (exact Fractions, engine weights,
no randomness needed: these are the exact odds). 300 honest groups at 0.25% of supply each; the
attacker splits a fixed holding over N **unlinked** wallets. "D39" uses the defaults (5% supply
cap, 5% odds cap, minimum 0.01% of supply per entrant); the last column lowers the minimum to
1e-9 of supply to show the pure linear invariance.

## Attacker holds 3% of supply (proportional share {_pct(proportional(int(SUPPLY * 3 // 100)))})

| wallets N | old isqrt odds | D39 odds | D39, minimum 1e-9 |
|---|---|---|---|
{rows(small)}

With linear odds the total is **identical for every N** while each piece is above the minimum;
1,000 pieces of 0.003% fall below the 0.01% minimum and get **0**. The old rule paid splitting.

## Attacker holds 20% of supply (proportional share {_pct(proportional(int(SUPPLY * 20 // 100)))})

| wallets N | old isqrt odds | D39 odds | D39, minimum 1e-9 |
|---|---|---|---|
{rows(whale)}

N = 1 is held to 5% of supply and then 5% of the odds. Splitting can escape the per-group caps,
but with linear odds the result is **never above the proportional share**; it is the cap's
known limit and no longer a profit from splitting itself.

## Proofs (COIN_MATH §9, D39)

1. Split invariance: weights are `w = s·D` (one common D), so N pieces with `Σ s_i = s` have
   `Σ w_i = w`; the total weight W is unchanged, so the odds `Σ w_i / W = w / W` are equal.
2. Merging never helps: `min(Σ b_i, C) ≤ Σ min(b_i, C)` (supply cap) and the odds cap is a
   `min` too, so a merged group's weight is ≤ the sum of its pieces' weights.
3. Splitting is bounded: each piece's weight is ≤ its uncapped linear weight, so a split group
   never exceeds its proportional share of the uncapped total.
4. Pieces below `0.01% · S` get 0, so dust spam costs 0.01% of supply per wallet and wins nothing.

Reproduce: `uv run python -m sim.rewards_d39_sybil > reports/rewards_d39_sybil_2026-11.md`
"""


def main() -> int:
    print(render_report(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
