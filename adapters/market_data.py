"""GTA 6 index measurements (INDEX_RULES §2–§3). Pure: no I/O and no clock.

F4 method (Helius Parsed Events, successor of Enhanced Transactions; field list
checked 2026-11-17 on the parsed-response docs):

`parsed.fee` is the Solana transaction fee in lamports. That one number is the
base fee plus the priority fee (`meta.fee`). Priority is not added a second time.
Tips are `nativeTransfers` whose destination is one of the eight Jito tip
accounts (`getTipAccounts` on docs.jito.wtf). A succeeded swap that moves the
mint contributes `fee + tips` once. Sums stay in lamports until the float SOL
fields. If the history walk stopped early, or a counted swap has no fee, both
SOL fields stay None, so a short history cannot pass the 10 SOL minimum.

Price, liquidity and the sample window are applied by the caller. Helius DAS
has no name search and no pool-liquidity field. DexScreener is only the
liquidity source, and the price source when DAS `price_info` is missing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

LAMPORTS_PER_SOL = 1_000_000_000


def lamports_to_sol(lamports: int) -> float:
    if lamports < 0:
        raise ValueError("negative lamports")
    return lamports / LAMPORTS_PER_SOL


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


def bundle_pct(
    txs: Sequence[Mapping[str, object]],
    mint: str,
    supply: int | None,
    excluded: Iterable[str],
) -> float | None:
    """Supply % bought in the creation slot by 2+ wallets. One wallet → 0. Unknown side → None."""
    if supply is None or supply <= 0:
        return None
    slots = [tx.get("slot") for tx in txs if isinstance(tx.get("slot"), int) and _moves(tx, mint)]
    if not slots:
        return None
    slot = min(int(s) for s in slots if isinstance(s, int))
    skip = set(excluded)
    bought: dict[str, int] = {}
    for tx in txs:
        if tx.get("slot") != slot:
            continue
        for row in _rows(tx):
            amount = row.get("amount")
            if row.get("mint") != mint or not isinstance(amount, int) or amount <= 0:
                continue
            dest = row.get("to")
            if not isinstance(dest, str) or not dest:
                return None
            if dest in skip:
                continue
            bought[dest] = bought.get(dest, 0) + amount
    if len(bought) < 2:
        return 0.0
    return 100 * sum(bought.values()) / supply


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
