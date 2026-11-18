"""Idempotent, verified payouts (D39, audit #271 M1/M4). Pure: no I/O, no clock.

Every transfer has a key `(epoch, draw, wallet)` written in the transaction memo as
`GTASP10:e<epoch>:d<draw>:<wallet>`. Before sending, the sender must pass both the local ledger
of keys already done and the memos found on-chain from the payout wallet; any key present in
either is never sent again. Keys whose intent was logged but whose result is unknown (crash
between send and save) block the whole batch until the on-chain check resolves them.
Draw payouts are only produced from a record that `verify_draw` reproduces exactly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from engine.draw_commit import DrawInputs, verify_draw, wallet_prizes

MEMO_PREFIX = "GTASP10"


def payment_key(epoch: int, draw: int, wallet: str) -> str:
    """draw = -1 for the daily holder rewards, the hourly draw_index otherwise."""
    if epoch < 0 or draw < -1 or not wallet:
        raise ValueError("epoch >= 0, draw >= -1, wallet required")
    return f"{MEMO_PREFIX}:e{epoch}:d{draw}:{wallet}"


class UnresolvedIntent(RuntimeError):
    """An earlier send has no known result: check the chain before sending anything."""


@dataclass(frozen=True)
class Send:
    key: str
    wallet: str
    amount: int


def pending_sends(
    due: Mapping[str, int],
    *,
    epoch: int,
    draw: int,
    done_keys: Iterable[str],
    onchain_memos: Iterable[str],
    open_intents: Iterable[str] = (),
) -> list[Send]:
    """Sends still owed. Never returns a key already done locally or seen on-chain."""
    done = set(done_keys) | set(onchain_memos)
    unresolved = sorted(set(open_intents) - done)
    if unresolved:
        raise UnresolvedIntent(f"{len(unresolved)} intent(s) without result: {unresolved[:3]}")
    out = []
    for wallet, amount in sorted(due.items()):
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(f"bad amount for {wallet}")
        key = payment_key(epoch, draw, wallet)
        if amount and key not in done:
            out.append(Send(key, wallet, amount))
    return out


def verified_draw_payouts(
    inputs: DrawInputs,
    committed: bytes,
    rho: bytes | None,
    *,
    vrf_requests: int,
    claimed_winners: list[str],
    claimed_prizes: Mapping[str, int],
    claimed_rollover: int,
    epoch: int,
    done_keys: Iterable[str],
    onchain_memos: Iterable[str],
    open_intents: Iterable[str] = (),
) -> list[Send]:
    """Verify the draw (raises DrawMismatch on any difference), then dedupe by key."""
    plan = verify_draw(
        inputs,
        committed,
        rho,
        vrf_requests=vrf_requests,
        claimed_winners=claimed_winners,
        claimed_prizes=claimed_prizes,
        claimed_rollover=claimed_rollover,
    )
    return pending_sends(
        wallet_prizes(inputs, plan),
        epoch=epoch,
        draw=inputs.draw_index,
        done_keys=done_keys,
        onchain_memos=onchain_memos,
        open_intents=open_intents,
    )
