"""Big-holder options for rewards weight (#342 C, #348): (a) pro-rata, (b) 5% cap, (c) sqrt.

A worked example for kiwi, not a rule change. Exact (Fractions, isqrt), no I/O, no floats.

Population at a €1M market cap (1B tokens, so €1 = 1,000 tokens):
one whale at 20% of supply, and 1,000 small holders: 600 × €100, 300 × €500, 100 × €1,500
(36% of supply). The rest (44%) is pool, curve, team and other excluded wallets.
Everyone has the same loyalty multiplier, so it cancels out of the shares.

    uv run python -m sim.big_holder_options   # prints the markdown tables used in the doc
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from fractions import Fraction
from math import isqrt

SUPPLY = 1_000_000_000  # whole tokens; base units do not change any share here
TOKENS_PER_EUR = 1_000  # €1M market cap
CAP = SUPPLY // 20  # (b): 5% of supply, like the draw (D39)
BUDGET_EUR = 1_000  # shares are shown per €1,000 of daily rewards
WHALE = SUPPLY // 5  # 20% of supply
SMALL_TIERS = ((600, 100), (300, 500), (100, 1_500))  # (holders, € each)
SPLITS = (1, 4, 10, 100)  # the whale's 20% spread over n wallets (sybil)

Weight = Callable[[int], int]


def pro_rata(balance: int) -> int:
    return balance


def capped(balance: int) -> int:
    return min(balance, CAP)


def sqrt_weight(balance: int) -> int:
    return isqrt(balance)


OPTIONS: tuple[tuple[str, Weight], ...] = (
    ("(a) pro-rata", pro_rata),
    ("(b) cap 5% of supply", capped),
    ("(c) sqrt", sqrt_weight),
)


def population(whale_wallets: int = 1) -> dict[str, int]:
    """Balances in whole tokens. The whale's amount is split evenly over `whale_wallets`."""
    part, rest = divmod(WHALE, whale_wallets)
    pop = {f"whale{i:03d}": part + (1 if i < rest else 0) for i in range(whale_wallets)}
    n = 0
    for count, eur in SMALL_TIERS:
        for _ in range(count):
            pop[f"small{n:04d}"] = eur * TOKENS_PER_EUR
            n += 1
    return pop


def shares(balances: Mapping[str, int], weight: Weight) -> dict[str, Fraction]:
    """Each wallet's exact share of the day's rewards; the shares sum to 1."""
    w = {k: weight(v) for k, v in balances.items()}
    total = sum(w.values())
    return {k: Fraction(v, total) for k, v in w.items()}


def whale_share(s: Mapping[str, Fraction]) -> Fraction:
    return sum((v for k, v in s.items() if k.startswith("whale")), Fraction(0))


def holder_100_share(s: Mapping[str, Fraction]) -> Fraction:
    return s["small0000"]  # the first tier is the €100 holders


def holder_1500_share(s: Mapping[str, Fraction]) -> Fraction:
    return s["small0900"]  # the last tier is the €1,500 holders


def pct(x: Fraction, places: int = 2) -> str:
    scaled = x * 100 * 10**places
    q = scaled.numerator // scaled.denominator  # floor
    return f"{q // 10**places}.{q % 10**places:0{places}d}%"


def eur(x: Fraction) -> str:
    cents = x * 100
    c = cents.numerator // cents.denominator  # floor to the cent
    return f"€{c // 100}.{c % 100:02d}"


def ratio(x: Fraction) -> str:
    h = x * 100
    q = h.numerator // h.denominator  # floor, in hundredths
    return f"×{q // 100}.{q % 100:02d}"


def table_options() -> str:
    pop = population()
    rows = [
        "| Option | Whale share | €100 holder share | €100 holder per €1,000 | vs (a) "
        "| €1,500 holder per €1,000 |",
        "|---|---|---|---|---|---|",
    ]
    base = holder_100_share(shares(pop, pro_rata))
    for name, fn in OPTIONS:
        s = shares(pop, fn)
        h = holder_100_share(s)
        rows.append(
            f"| {name} | {pct(whale_share(s))} | {pct(h, 4)} | {eur(h * BUDGET_EUR)} | "
            f"{ratio(h / base)} | {eur(holder_1500_share(s) * BUDGET_EUR)} |"
        )
    return "\n".join(rows)


def table_sybil() -> str:
    head = " | ".join(f"{name}" for name, _ in OPTIONS)
    rows = [
        f"| Whale wallets | {head} |",
        "|---|" + "---|" * len(OPTIONS),
    ]
    for n in SPLITS:
        pop = population(n)
        cells = []
        for _, fn in OPTIONS:
            s = shares(pop, fn)
            cells.append(f"{pct(whale_share(s))} / {eur(holder_100_share(s) * BUDGET_EUR)}")
        rows.append(f"| {n} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def main() -> None:
    print("Whale 20% in one wallet (cells: whale share / €100 holder per €1,000):\n")
    print(table_options())
    print("\nWhale splits its 20% over n wallets (cells: whale share / €100 holder per €1,000):\n")
    print(table_sybil())


if __name__ == "__main__":
    main()
