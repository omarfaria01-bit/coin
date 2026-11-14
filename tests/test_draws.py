"""Tests for engine/draws.py (ENGINE_DESIGN §5, COIN_MATH §9)."""

from __future__ import annotations

import math
import time
from collections import Counter
from hashlib import sha256

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.draws import draw_winners, split_prizes, uniform_from
from engine.params import DrawParams

# Default ranks: 1×40% + 3×10% + 6×5%.
SPLIT = DrawParams().prize_split

# Chi-square, 2 df, alpha = 0.001 (critical value 13.81551). First-pick
# frequency must follow t_c = sqrt(s_c). 20_000 independent seeds.
CHI2_ALPHA = 0.001
CHI2_DF2_CRIT = 13.81551
N_SEEDS = 20_000
STAT_SCORES = {"A": 1.0, "B": 4.0, "C": 9.0}  # t = 1, 2, 3; P(first) = 1/6, 2/6, 3/6


def _u_manual(randomness: bytes, cluster_id: str) -> float:
    n = int.from_bytes(sha256(randomness + cluster_id.encode("utf-8")).digest()[:8], "big")
    return (n + 0.5) / (1 << 64)


def test_uniform_from_is_open_unit_interval_and_matches_spec() -> None:
    for randomness, cid in ((b"", "A"), (b"seed", "cluster"), (bytes(32), "1" * 44)):
        u = uniform_from(randomness, cid)
        assert 0.0 < u < 1.0
        assert u == _u_manual(randomness, cid)


def test_draw_is_deterministic_and_changes_with_randomness() -> None:
    scores = {"c": 3.0, "a": 1.0, "b": 2.0, "z": 0.0, "neg": -5.0}
    a = draw_winners(scores, b"seed-1", 3)
    b = draw_winners(scores, b"seed-1", 3)
    c = draw_winners(scores, b"seed-2", 3)
    assert a == b
    assert set(a) <= {"a", "b", "c"}
    assert len(a) == len(set(a)) == 3
    assert c != a  # two independent 32-bit-ish streams colliding on a 3-set is negligible


def test_k_greater_than_n_and_non_positive_k_or_scores() -> None:
    scores = {"x": 1.0, "y": 2.0, "zero": 0.0, "neg": -1.0}
    winners = draw_winners(scores, b"k", 10)
    assert winners == draw_winners({"x": 1.0, "y": 2.0}, b"k", 2)
    assert len(winners) == 2 and len(set(winners)) == 2
    assert draw_winners(scores, b"k", 0) == []
    assert draw_winners(scores, b"k", -3) == []
    assert draw_winners({"a": 0.0, "b": -2.0}, b"k", 5) == []


def test_ties_broken_by_cluster_id_ascending() -> None:
    # Equal keys would sort by id. Construct via equal score is not enough (u differs),
    # so we only assert the sort key form: (-key, id) — equal-key order is id asc.
    # Two ids with identical u only if hashes collide; instead compare key tuples.
    randomness = b"tie"
    scores = {"b": 1.0, "a": 1.0}
    keys = {
        cid: math.log(uniform_from(randomness, cid)) / math.sqrt(score)
        for cid, score in scores.items()
    }
    expected = sorted(scores, key=lambda cid: (-keys[cid], cid))
    assert draw_winners(scores, randomness, 2) == expected


def test_split_prizes_conserves_pot_and_keeps_unused_shares() -> None:
    winners = [f"w{i}" for i in range(10)]
    prizes, rem = split_prizes(1_000_000, winners, SPLIT)
    assert sum(prizes.values()) + rem == 1_000_000
    assert prizes["w0"] == 400_000
    assert prizes["w1"] == 100_000
    assert prizes["w9"] == 50_000
    assert rem == 0

    # Fewer winners than ranks: unused shares stay in the pot.
    prizes, rem = split_prizes(1_000_000, ["only"], SPLIT)
    assert prizes == {"only": 400_000}
    assert rem == 600_000

    # More winners than ranks: extra ids get nothing; floor dust stays in pot.
    prizes, rem = split_prizes(10, ["a", "b", "c"], (0.40, 0.10))
    assert prizes == {"a": 4, "b": 1}
    assert rem == 5
    assert "c" not in prizes

    prizes, rem = split_prizes(0, winners, SPLIT)
    assert rem == 0 and all(v == 0 for v in prizes.values())
    prizes, rem = split_prizes(7, [], SPLIT)
    assert prizes == {} and rem == 7


@given(
    st.dictionaries(
        st.text(
            min_size=1,
            max_size=8,
            alphabet="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
        ),
        st.floats(min_value=-10.0, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=15,
    ),
    st.binary(min_size=0, max_size=32),
    st.integers(min_value=-2, max_value=20),
)
@settings(max_examples=60, deadline=None)
def test_draw_ignores_input_order(scores: dict[str, float], randomness: bytes, k: int) -> None:
    items = list(scores.items())
    shuffled = dict(reversed(items))
    assert draw_winners(shuffled, randomness, k) == draw_winners(scores, randomness, k)
    winners = draw_winners(scores, randomness, k)
    assert len(winners) == len(set(winners))
    eligible = {cid for cid, s in scores.items() if s > 0}
    assert set(winners) <= eligible
    assert len(winners) == min(max(k, 0), len(eligible))


def test_first_pick_frequency_matches_sqrt_score() -> None:
    """Chi-square goodness-of-fit, df=2, alpha=0.001, N=20_000.

    Scores A=1, B=4, C=9 → t=1,2,3 → first-pick probabilities 1/6, 2/6, 3/6.
    randomness_i = i.to_bytes(8, 'big'). Fail if chi2 > 13.81551.
    """
    t_weights = {cid: math.sqrt(s) for cid, s in STAT_SCORES.items()}
    total_t = sum(t_weights.values())
    t0 = time.perf_counter()
    counts: Counter[str] = Counter()
    for i in range(N_SEEDS):
        seed = i.to_bytes(8, "big")
        counts[draw_winners(STAT_SCORES, seed, 1)[0]] += 1
    elapsed = time.perf_counter() - t0
    chi2 = 0.0
    for cid, t in t_weights.items():
        expected = N_SEEDS * t / total_t
        chi2 += (counts[cid] - expected) ** 2 / expected
    assert elapsed < 10.0, f"statistical test took {elapsed:.3f}s"
    assert chi2 <= CHI2_DF2_CRIT, (
        f"chi2={chi2:.3f} > {CHI2_DF2_CRIT} (alpha={CHI2_ALPHA}, df=2, n={N_SEEDS}, "
        f"counts={dict(counts)})"
    )
    print(
        f"\nfirst-pick chi2={chi2:.3f} (crit {CHI2_DF2_CRIT}) "
        f"in {elapsed:.3f}s counts={dict(counts)}"
    )


@pytest.mark.parametrize("pot", [1, 7, 99, 1_000_000_000])
def test_split_conservation_parametrized(pot: int) -> None:
    winners = [f"w{i}" for i in range(len(SPLIT))]
    prizes, rem = split_prizes(pot, winners, SPLIT)
    assert sum(prizes.values()) + rem == pot
    assert rem >= 0


def test_split_prizes_rejects_duplicate_winners() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        split_prizes(100, ["a", "a"], (0.4, 0.1))


def test_split_prizes_rejects_negative_pot() -> None:
    with pytest.raises(ValueError, match="pot"):
        split_prizes(-1, ["a"], (0.4,))


def test_split_prizes_rejects_negative_share() -> None:
    with pytest.raises(ValueError, match="prize_split"):
        split_prizes(100, ["a"], (0.4, -0.1))


def test_split_prizes_rejects_shares_sum_over_one() -> None:
    with pytest.raises(ValueError, match="prize_split"):
        split_prizes(100, ["a", "b"], (0.6, 0.5))


def test_draw_winners_rejects_non_finite_score() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        draw_winners({"a": 1.0, "b": float("nan")}, b"seed", 1)
    with pytest.raises(ValueError, match="non-finite"):
        draw_winners({"a": float("inf")}, b"seed", 1)
