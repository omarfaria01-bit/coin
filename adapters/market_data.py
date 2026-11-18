"""GTA 6 index measurements (INDEX_RULES §2–§3). Pure: no I/O and no clock.

F4 method (Helius Parsed Events, successor of Enhanced Transactions; field list
checked 2026-11-17 on the parsed-response docs):

`parsed.fee` is the Solana transaction fee in lamports. That one number is the
base fee plus the priority fee (`meta.fee`). Priority is not added a second time.
Tips are `nativeTransfers` whose destination is one of the eight Jito tip
accounts (`getTipAccounts` on docs.jito.wtf). A succeeded swap that moves the
mint contributes `fee + tips` once. Sums stay in lamports until the float SOL
fields. If the history walk stopped early, or a counted swap has no fee, both
SOL fields stay None, so a short history cannot pass the 8 SOL minimum.

Price, liquidity and the sample window are applied by the caller. Helius DAS
has no name search and no pool-liquidity field. DexScreener is only the
liquidity source, and the price source when DAS `price_info` is missing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

LAMPORTS_PER_SOL = 1_000_000_000


def lamports_to_sol(lamports: int) -> float:
    if lamports < 0:
        raise ValueError("negative lamports")
    return lamports / LAMPORTS_PER_SOL


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def market_cap_usd(
    price: float | None, supply_raw: int | None, decimals: int | None
) -> float | None:
    """Whole-token USD price times UI supply. Missing or non-finite inputs stay None."""
    px = _finite(price)
    if px is None or supply_raw is None or decimals is None or supply_raw < 0 or decimals < 0:
        return None
    cap = px * supply_raw / 10**decimals
    return cap if math.isfinite(cap) else None


def mean(values: Iterable[float]) -> float | None:
    rows = [v for v in values if _finite(v) is not None]
    if not rows:
        return None
    return sum(rows) / len(rows)


def median(values: Sequence[float]) -> float | None:
    rows = sorted(v for v in values if _finite(v) is not None)
    if not rows:
        return None
    mid = len(rows) // 2
    if len(rows) % 2:
        return rows[mid]
    return (rows[mid - 1] + rows[mid]) / 2


def coverage(times: Iterable[int], start: int, end: int, bucket_seconds: int) -> float:
    """Share of `[start, end)` buckets that contain a sample. Empty window → 0."""
    if bucket_seconds <= 0 or end <= start:
        return 0.0
    expected = max(1, (end - start) // bucket_seconds)
    filled = {
        (t - start) // bucket_seconds
        for t in times
        if start <= t < end and 0 <= (t - start) // bucket_seconds < expected
    }
    return len(filled) / expected


@dataclass(frozen=True)
class Sample:
    mint: str
    t: int
    mc_usd: float | None = None
    liquidity_usd: float | None = None
    volume_usd: float | None = None
    top10_pct: float | None = None


@dataclass(frozen=True)
class WindowStats:
    coverage: float
    mc_usd: float | None
    liquidity_usd: float | None
    volume_usd: float | None
    top10_pct: float | None


def aggregate_samples(
    samples: Sequence[Sample],
    start: int,
    end: int,
    sample_seconds: int,
    holder_seconds: int,
) -> WindowStats:
    """Means of MC and liquidity. Volume is the latest h24 reading, already a window sum.

    Top-10 is the median of the last holder sample in each holder bucket.
    """
    rows = [s for s in samples if start <= s.t < end]
    vol = [s for s in rows if _finite(s.volume_usd) is not None]
    per_bucket: dict[int, float] = {}
    for row in rows:
        pct = _finite(row.top10_pct)
        if pct is None or holder_seconds <= 0:
            continue
        per_bucket[row.t // holder_seconds] = pct
    latest = max(vol, key=lambda s: s.t).volume_usd if vol else None
    return WindowStats(
        coverage=coverage((s.t for s in rows), start, end, sample_seconds),
        mc_usd=mean(s.mc_usd for s in rows if s.mc_usd is not None),
        liquidity_usd=mean(s.liquidity_usd for s in rows if s.liquidity_usd is not None),
        volume_usd=latest,
        top10_pct=median(list(per_bucket.values())),
    )


def pick_pair(pairs: Sequence[Mapping[str, object]], mint: str) -> Mapping[str, object] | None:
    """Deepest DexScreener pair whose base token is `mint`. Missing liquidity sorts last."""
    best: Mapping[str, object] | None = None
    best_liq = -1.0
    for pair in pairs:
        base = pair.get("baseToken")
        if not isinstance(base, Mapping) or base.get("address") != mint:
            continue
        liq = pair.get("liquidity")
        usd = liq.get("usd") if isinstance(liq, Mapping) else None
        score = _finite(usd)
        rank = score if score is not None else -1.0
        if best is None or rank > best_liq:
            best, best_liq = pair, rank
    return best


def trades_mint(tx: Mapping[str, object], mint: str) -> bool:
    """True for one succeeded swap that moves `mint`. Transfers and failed txs do not count."""
    if tx.get("ok") is not True or tx.get("summary") != "swap":
        return False
    transfers = tx.get("transfers")
    if not isinstance(transfers, list):
        return False
    return any(
        isinstance(row, Mapping)
        and row.get("mint") == mint
        and isinstance(row.get("amount"), int)
        and row["amount"] > 0
        for row in transfers
    )


@dataclass(frozen=True)
class FeeTotals:
    """Lamport sums. SOL fields are None when the walk is incomplete (never an under-count)."""

    lifetime_lamports: int | None
    window_lamports: int | None
    traders: frozenset[str] | None

    @property
    def total_fees_sol(self) -> float | None:
        if self.lifetime_lamports is None:
            return None
        return lamports_to_sol(self.lifetime_lamports)

    @property
    def window_fees_sol(self) -> float | None:
        if self.window_lamports is None:
            return None
        return lamports_to_sol(self.window_lamports)


def fee_totals(
    txs: Sequence[Mapping[str, object]],
    mint: str,
    *,
    window_start: int,
    window_end: int,
    truncated: bool,
) -> FeeTotals:
    """Sum trader fees once per signature. `truncated` or a missing fee blanks every total."""
    if truncated:
        return FeeTotals(None, None, None)
    seen: set[str] = set()
    lifetime = 0
    window = 0
    payers: set[str] = set()
    window_ok = True
    for tx in txs:
        sig = tx.get("signature")
        if not isinstance(sig, str) or sig in seen or not trades_mint(tx, mint):
            continue
        seen.add(sig)
        fee = tx.get("fee")
        tips = tx.get("tips")
        if not isinstance(fee, int) or not isinstance(tips, int) or fee < 0 or tips < 0:
            return FeeTotals(None, None, None)
        paid = fee + tips
        lifetime += paid
        when = tx.get("block_time")
        if not isinstance(when, int):
            window_ok = False
            continue
        if window_start <= when < window_end:
            window += paid
            payer = tx.get("fee_payer")
            if not isinstance(payer, str) or not payer:
                window_ok = False
            else:
                payers.add(payer)
    if not window_ok:
        return FeeTotals(lifetime, None, None)
    return FeeTotals(lifetime, window, frozenset(payers))


@dataclass(frozen=True)
class TradeQuality:
    """F9/F10 inputs from the swaps in the window (#170, D33). Lamports in, ratios out."""

    independent_traders: int
    roundtrip_share: float  # 0..1 of window SOL volume matched as same-wallet round trips
    volume_wallets: int  # wallets with volume left after removing round trips
    median_trade_sol: float | None  # median remaining trade, None when nothing remains


def trade_quality(
    txs: Sequence[Mapping[str, object]],
    mint: str,
    *,
    window_start: int,
    window_end: int,
    truncated: bool,
    creator: str | None,
    min_trader_lamports: int,
    roundtrip_seconds: int,
) -> TradeQuality | None:
    """Per-wallet SOL volume and round trips. None when the walk is incomplete or any counted
    swap has an unknown wallet, side or SOL amount (fail closed: never a flattering count).

    Side: the fee payer receives the mint = buy (SOL out), sends it = sell (SOL in).
    The creator wallet never counts as an independent trader.
    """
    if truncated:
        return None
    seen: set[str] = set()
    trades: dict[str, list[tuple[int, int, int]]] = {}  # wallet -> (time, side, lamports)
    for tx in txs:
        sig = tx.get("signature")
        when = tx.get("block_time")
        if not isinstance(sig, str) or sig in seen or not trades_mint(tx, mint):
            continue
        seen.add(sig)
        if not isinstance(when, int):
            return None
        if not window_start <= when < window_end:
            continue
        payer = tx.get("fee_payer")
        out, got = tx.get("sol_out"), tx.get("sol_in")
        if not isinstance(payer, str) or not isinstance(out, int) or not isinstance(got, int):
            return None
        moves = [
            r for r in tx.get("transfers") or [] if isinstance(r, Mapping) and r.get("mint") == mint
        ]  # type: ignore[union-attr]
        bought = any(r.get("to") == payer for r in moves)
        sold = any(r.get("from") == payer for r in moves)
        if bought == sold:
            return None
        side, lamports = (1, out) if bought else (-1, got)
        if lamports > 0:
            trades.setdefault(payer, []).append((when, side, lamports))
    total = 0
    matched = 0
    independent = 0
    left: list[int] = []
    wallets_left = 0
    for wallet, rows in trades.items():
        volume = sum(r[2] for r in rows)
        total += volume
        if wallet != creator and volume >= min_trader_lamports:
            independent += 1
        open_: list[list[int]] = []  # unmatched [time, side, remaining]
        for when, side, lamports in sorted(rows):
            for prev in open_:
                if lamports == 0:
                    break
                if prev[1] == -side and prev[2] > 0 and when - prev[0] <= roundtrip_seconds:
                    take = min(prev[2], lamports)
                    prev[2] -= take
                    lamports -= take
                    matched += 2 * take
            if lamports > 0:
                open_.append([when, side, lamports])
        rest = [r[2] for r in open_ if r[2] > 0]
        if rest:
            wallets_left += 1
            left.extend(rest)
    left.sort()
    median = lamports_to_sol(left[(len(left) - 1) // 2]) if left else None
    share = matched / total if total else 0.0
    return TradeQuality(independent, share, wallets_left, median)


def top10_pct(
    holders: Sequence[tuple[str | None, int]],
    supply: int | None,
    excluded: Iterable[str],
) -> float | None:
    """Percent of supply held by the 10 largest non-excluded owners. Unknown owner → None."""
    if supply is None or supply <= 0:
        return None
    skip = set(excluded)
    kept: list[int] = []
    for owner, amount in holders:
        if amount < 0 or owner is None:
            return None
        if owner in skip:
            continue
        kept.append(amount)
    kept.sort(reverse=True)
    return 100 * sum(kept[:10]) / supply


BUNDLE_WINDOW_SLOTS = 10  # D31: ~4 s; a next-slot sniper is inside, a Jito bundle too


def bundle_pct(
    txs: Sequence[Mapping[str, object]],
    mint: str,
    supply: int | None,
    excluded: Iterable[str],
    *,
    creator: str | None = None,
    window_slots: int = BUNDLE_WINDOW_SLOTS,
) -> float | None:
    """Supply % bought in the first `window_slots` slots by any non-excluded wallet except the
    creator (the creator's own buy is F6's `dev_pct`). One sniper counts. Unknown side → None.
    """
    if supply is None or supply <= 0 or window_slots < 1:
        return None
    slots = [tx.get("slot") for tx in txs if isinstance(tx.get("slot"), int) and _moves(tx, mint)]
    if not slots:
        return None
    first = min(int(s) for s in slots if isinstance(s, int))
    skip = set(excluded)
    if creator:
        skip.add(creator)
    total = 0
    for tx in txs:
        slot = tx.get("slot")
        if not isinstance(slot, int) or not first <= slot < first + window_slots:
            continue
        for row in _rows(tx):
            amount = row.get("amount")
            if row.get("mint") != mint or not isinstance(amount, int) or amount <= 0:
                continue
            dest = row.get("to")
            if not isinstance(dest, str) or not dest:
                return None
            if dest not in skip:
                total += amount
    return 100 * total / supply


def creator_launches(
    creates: Sequence[Mapping[str, object]],
    creator: str | None,
    start: int,
    end: int,
    *,
    truncated: bool,
) -> int | None:
    """Distinct mints this creator launched in `[start, end)`. A short history stays None."""
    if truncated or not creator:
        return None
    mints: set[str] = set()
    for row in creates:
        when = row.get("block_time")
        mint = row.get("mint")
        if row.get("creator") != creator or not isinstance(when, int):
            continue
        if not start <= when < end or not isinstance(mint, str) or not mint:
            continue
        mints.add(mint)
    return len(mints)


def authorities_revoked(info: Mapping[str, object] | None) -> tuple[bool | None, bool | None]:
    """`(mint_revoked, freeze_revoked)`. A missing key is unknown, not revoked."""
    if not isinstance(info, Mapping):
        return None, None

    def flag(key: str) -> bool | None:
        if key not in info:
            return None
        value = info[key]
        if value is None:
            return True
        if isinstance(value, str) and value:
            return False
        return None

    return flag("mintAuthority"), flag("freezeAuthority")


def _rows(tx: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = tx.get("transfers")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, Mapping)]


def _moves(tx: Mapping[str, object], mint: str) -> bool:
    return any(row.get("mint") == mint for row in _rows(tx))
