"""Pot smoothing, whale cap water-filling, payouts (COIN_MATH §6, §8). Owner: Grok."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from engine.loyalty import loyalty_scores
from engine.types import ClusterId, WalletId

# Rent-exempt minimum of a 170-byte Token-2022 ATA (ImmutableOwner), measured on
# mainnet (reports/research_token2022_claims_2026-11.md). A basket payout worth
# less than this does not open a token account; the amount carries.
TOKEN_ACCOUNT_RENT_LAMPORTS = 1_513_840


def epoch_budget_v033(pot: int, alpha: Fraction) -> int:
    """R_e = floor(α · Pot_e) for the fixed 86,400 s epoch (COIN_MATH v0.3.3 §0, §8).

    Exact integers only; 0 < α ≤ 1, so 0 ≤ R_e ≤ Pot_e.
    """
    if isinstance(pot, bool) or not isinstance(pot, int):
        raise TypeError("pot must be an int (Q base units)")
    if pot < 0:
        raise ValueError(f"pot must be >= 0, got {pot}")
    if not isinstance(alpha, Fraction) or not 0 < alpha <= 1:
        raise ValueError(f"alpha must be a Fraction in (0, 1], got {alpha!r}")
    return pot * alpha.numerator // alpha.denominator


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §6. Whale cap with uplift limit G=2. Leftover stays in the pot.
# ---------------------------------------------------------------------------

DEFAULT_CAP = Fraction(1, 20)
DEFAULT_G = Fraction(2)


def _score_frac(value: int | Fraction) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int | Fraction):
        raise TypeError("score must be an int or Fraction")
    return value if isinstance(value, Fraction) else Fraction(value)


def capped_shares_v033(
    scores: Mapping[ClusterId, int | Fraction],
    cap: int | Fraction = DEFAULT_CAP,
    g: int | Fraction = DEFAULT_G,
) -> dict[ClusterId, Fraction]:
    """π_c = min(CAP, θ · s_c) with θ = min(θ*, G/S). rollover_share = 1 − Σπ_c.

    If S = 0, every share is 0 and no division is performed. θ* is the
    water-filling scale, or unbounded when N · CAP ≤ 1.
    """
    cap_f = _score_frac(cap)
    g_f = _score_frac(g)
    if cap_f <= 0 or cap_f > 1:
        raise ValueError(f"cap must be in (0, 1], got {cap_f}")
    if g_f <= 0:
        raise ValueError(f"G must be > 0, got {g_f}")
    ids = sorted(scores)
    raw = {cid: _score_frac(scores[cid]) for cid in ids}
    out = {cid: Fraction(0) for cid in ids}
    positive = {cid: s for cid, s in raw.items() if s > 0}
    if not positive:
        return out
    total = sum(positive.values(), Fraction(0))
    # Water-fill θ*. Unbounded if even capping everyone cannot fill the unit mass.
    uncapped = set(positive)
    capped_n = 0
    theta_star: Fraction | None
    max_iter = len(positive) + 1
    for _ in range(max_iter):
        if not uncapped:
            theta_star = None
            break
        mass = 1 - capped_n * cap_f
        if mass <= 0:
            theta_star = None
            break
        free = sum((positive[cid] for cid in uncapped), Fraction(0))
        trial = mass / free
        overflow = {cid for cid in uncapped if trial * positive[cid] > cap_f}
        if not overflow:
            theta_star = trial
            break
        capped_n += len(overflow)
        uncapped -= overflow
    else:
        raise ValueError("capped_shares_v033 exceeded N iterations")
    theta = g_f / total if theta_star is None else min(theta_star, g_f / total)
    for cid, score in positive.items():
        out[cid] = min(cap_f, theta * score)
    return out


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §6 "Exact payout (integers)" and "Per-wallet split".
# Integers and Fractions only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExactPayout:
    """Result of the exact §6 payout. ``Σ payouts + rollover_units == r_e``."""

    payouts: dict[ClusterId, int]
    total: int  # T = floor(R_e · Σ π_c)
    rollover_units: int  # R_e − T, stays in the pot


def _largest_remainder(budget: int, weights: Mapping[str, Fraction], total: int) -> dict[str, int]:
    """floor(budget · w) each, then ``total − Σ floors`` single units by largest
    remainder, ties by id (ascending string order). Requires Σ w ≤ 1 and
    ``total ≤ floor(budget · Σ w)``, so the leftover is < the number of ids.
    """
    out: dict[str, int] = {}
    rems: list[tuple[Fraction, str]] = []
    for key in sorted(weights):
        exact = budget * weights[key]
        base = exact.numerator // exact.denominator
        out[key] = base
        rems.append((exact - base, key))
    leftover = total - sum(out.values())
    if leftover < 0 or leftover > len(rems):
        raise ValueError(f"leftover {leftover} out of range for {len(rems)} ids")
    rems.sort(key=lambda r: (-r[0], r[1]))
    for _rem, key in rems[:leftover]:
        out[key] += 1
    return out


def exact_payout(r_e: int, shares: Mapping[ClusterId, Fraction]) -> ExactPayout:
    """§6 steps 1–5. ``shares`` are π_c from :func:`capped_shares_v033`.

    S = 0 (every share 0): nothing is paid and the whole R_e rolls over.
    """
    if isinstance(r_e, bool) or not isinstance(r_e, int):
        raise TypeError("R_e must be an int (Q base units)")
    if r_e < 0:
        raise ValueError(f"R_e must be >= 0, got {r_e}")
    pis = {cid: _score_frac(pi) for cid, pi in shares.items()}
    if any(pi < 0 for pi in pis.values()):
        raise ValueError("shares must be >= 0")
    sigma = sum(pis.values(), Fraction(0))
    if sigma > 1:
        raise ValueError(f"Σ shares must be <= 1, got {sigma}")
    exact_total = r_e * sigma
    total = exact_total.numerator // exact_total.denominator
    payouts = _largest_remainder(r_e, pis, total)
    rollover = r_e - total
    if sum(payouts.values()) + rollover != r_e:  # pragma: no cover - invariant
        raise AssertionError("payout conservation violated")
    return ExactPayout(payouts=payouts, total=total, rollover_units=rollover)


def split_cluster_payout(
    payout_c: int, wallet_scores: Mapping[WalletId, int | Fraction]
) -> dict[WalletId, int]:
    """Per-wallet split of one cluster's payout (§6): floor(payout_c · s_w / s_c),
    leftovers by largest remainder, ties by wallet address. Σ == payout_c.

    ``s_w`` is the part of ``s_c`` from lots physically held in ``w``.
    """
    if isinstance(payout_c, bool) or not isinstance(payout_c, int) or payout_c < 0:
        raise ValueError(f"payout_c must be an int >= 0, got {payout_c!r}")
    s_w = {wid: _score_frac(s) for wid, s in wallet_scores.items()}
    if any(s < 0 for s in s_w.values()):
        raise ValueError("wallet scores must be >= 0")
    s_c = sum(s_w.values(), Fraction(0))
    if s_c == 0:
        if payout_c:
            raise ValueError("a cluster with zero score cannot receive a payout")
        return {wid: 0 for wid in sorted(s_w)}
    return _largest_remainder(payout_c, {w: s / s_c for w, s in s_w.items()}, payout_c)


def allocate_holder_rewards(
    budget: int,
    balances: Mapping[str, int],
    hold_seconds: Mapping[str, int],
) -> dict[str, int]:
    """Today's holder budget split by `loyalty_weight` (balance × loyalty multiplier).

    Σ == budget when anyone has held for at least 1h. Otherwise nobody is credited
    and the caller keeps the budget in the pot. Integer, largest remainder.
    """
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError(f"budget must be an int >= 0, got {budget!r}")
    scores = loyalty_scores(balances, hold_seconds)
    if budget == 0 or not any(scores.values()):
        return {w: 0 for w in scores}
    return split_cluster_payout(budget, scores)


@dataclass(frozen=True, slots=True)
class DailyRewards:
    """One daily settlement. ``paid + carry == previous carry + credit`` per wallet."""

    paid: dict[str, int]
    carry: dict[str, int]
    last_paid_day: dict[str, int]


def settle_daily_rewards(
    carry: Mapping[str, int],
    credit: Mapping[str, int],
    worth_lamports: Mapping[str, int],
    *,
    day_index: int,
    last_paid_day: Mapping[str, int] | None = None,
    min_payout_lamports: int = TOKEN_ACCOUNT_RENT_LAMPORTS,
) -> DailyRewards:
    """Accrue per holder and pay at most once per `day_index`.

    ``worth_lamports[w]`` is the SOL value of that holder's accrued basket-coin
    position (carry + credit). Worth below the token-account rent is carried and
    no account is opened. A configured minimum under the rent is raised to the rent.
    """
    if isinstance(day_index, bool) or not isinstance(day_index, int):
        raise TypeError("day_index must be an int")
    if min_payout_lamports < 0:
        raise ValueError("min_payout_lamports must be >= 0")
    floor = max(min_payout_lamports, TOKEN_ACCOUNT_RENT_LAMPORTS)
    paid_on = dict(last_paid_day or {})
    paid: dict[str, int] = {}
    new_carry: dict[str, int] = {}
    new_days = dict(paid_on)
    for w in sorted(set(carry) | set(credit)):
        prev, add = carry.get(w, 0), credit.get(w, 0)
        worth = worth_lamports.get(w, 0)
        if prev < 0 or add < 0 or worth < 0:
            raise ValueError("amounts and worth must be >= 0")
        accrued = prev + add
        if accrued == 0 or paid_on.get(w) == day_index or worth < floor:
            if accrued:
                new_carry[w] = accrued
            continue
        paid[w] = accrued
        new_days[w] = day_index
    return DailyRewards(paid, new_carry, new_days)
