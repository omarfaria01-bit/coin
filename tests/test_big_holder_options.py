"""#348 C: big-holder options example (sim/big_holder_options.py) stays exact and honest."""

from __future__ import annotations

from fractions import Fraction

from sim.big_holder_options import (
    CAP,
    OPTIONS,
    SUPPLY,
    WHALE,
    capped,
    holder_100_share,
    population,
    pro_rata,
    shares,
    sqrt_weight,
    whale_share,
)


def test_population_is_conserved_under_splits() -> None:
    for n in (1, 3, 4, 7, 100):
        pop = population(n)
        assert sum(v for k, v in pop.items() if k.startswith("whale")) == WHALE
        assert len(pop) == n + 1_000
        assert sum(pop.values()) == WHALE + SUPPLY * 36 // 100


def test_shares_sum_to_one_for_every_option() -> None:
    for n in (1, 10):
        for _, fn in OPTIONS:
            assert sum(shares(population(n), fn).values()) == Fraction(1)


def test_one_wallet_numbers_match_the_doc() -> None:
    pop = population()
    assert whale_share(shares(pop, pro_rata)) == Fraction(20, 56)  # 20% of the 56% held
    assert whale_share(shares(pop, capped)) == Fraction(5, 41)  # cap 5% vs 36% small
    assert holder_100_share(shares(pop, pro_rata)) == Fraction(1, 5_600)
    # The €100 holder gains under (b) and more under (c).
    a, b, c = (holder_100_share(shares(pop, fn)) for _, fn in OPTIONS)
    assert a < b < c


def test_sybil_split_undoes_the_cap_and_weakens_sqrt() -> None:
    one, four = population(1), population(4)
    assert all(v <= CAP for k, v in four.items() if k.startswith("whale"))
    assert shares(four, capped) == shares(four, pro_rata)  # (b) fully undone at 4 wallets
    s1 = whale_share(shares(one, sqrt_weight))
    s100 = whale_share(shares(population(100), sqrt_weight))
    assert s100 > 5 * s1  # (c) weakened a lot, not fully undone
    assert s100 < whale_share(shares(one, pro_rata))
