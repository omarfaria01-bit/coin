"""Deterministic agents that emit engine-typed events against a constant-product pool."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from engine.types import EventKind, FirstFunding, SolTransfer, TokenEvent, WalletId
from sim.market import ConstantProductPool

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def wallet_id(label: str) -> WalletId:
    """Stable 32-byte base58 id derived from a label (no extra dependency)."""
    raw = sha256(b"sim-wallet:" + label.encode()).digest()
    n = int.from_bytes(raw, "big")
    chars: list[str] = []
    while n:
        n, r = divmod(n, 58)
        chars.append(_B58[r])
    pad = 0
    for b in raw:
        if b == 0:
            pad += 1
        else:
            break
    return _B58[0] * pad + "".join(reversed(chars or [_B58[0]]))


@dataclass
class Books:
    events: list[TokenEvent] = field(default_factory=list)
    sol_transfers: list[SolTransfer] = field(default_factory=list)
    fundings: list[FirstFunding] = field(default_factory=list)
    funded: set[WalletId] = field(default_factory=set)


class Clock:
    """Deterministic (slot, sig, ix) stamps; 1 slot per second from start_ts."""

    def __init__(self, start_ts: int, start_slot: int = 1, seed: int = 0) -> None:
        self.start_ts = start_ts
        self.start_slot = start_slot
        self.seed = seed
        self._ix: dict[str, int] = {}

    def stamp(self, ts: int, tag: str) -> tuple[int, str, int]:
        slot = self.start_slot + (ts - self.start_ts)
        sig = sha256(f"{self.seed}:{ts}:{tag}".encode()).hexdigest()
        ix = self._ix.get(sig, 0)
        self._ix[sig] = ix + 1
        return slot, sig, ix


def _fund(
    books: Books, clock: Clock, ts: int, funder: WalletId, wallet: WalletId, lamports: int
) -> None:
    slot, sig, _ix = clock.stamp(ts, f"fund:{wallet}")
    books.sol_transfers.append(SolTransfer(slot, ts, sig, funder, wallet, lamports))
    if wallet not in books.funded:
        books.fundings.append(FirstFunding(wallet, funder, ts, ts))
        books.funded.add(wallet)


def _buy(
    books: Books,
    clock: Clock,
    ts: int,
    pool: ConstantProductPool,
    wallet: WalletId,
    lamports: int,
) -> int:
    tokens = pool.buy(lamports)
    slot, sig, ix = clock.stamp(ts, f"buy:{wallet}")
    books.events.append(
        TokenEvent(slot, ts, sig, ix, EventKind.BUY, None, wallet, tokens, lamports, wallet)
    )
    return tokens


def _sell(
    books: Books,
    clock: Clock,
    ts: int,
    pool: ConstantProductPool,
    wallet: WalletId,
    tokens: int,
) -> int:
    lamports = pool.sell(tokens)
    slot, sig, ix = clock.stamp(ts, f"sell:{wallet}")
    books.events.append(
        TokenEvent(slot, ts, sig, ix, EventKind.SELL, wallet, None, tokens, lamports, wallet)
    )
    return lamports


@dataclass
class Holder:
    """Buys once at `buy_ts` and holds. Also used for whale-split, pump, and farmer."""

    label: str
    funder: str
    buy_lamports: int
    buy_ts: int
    tokens: int = 0
    sol: int = 0
    _done: bool = False

    def __post_init__(self) -> None:
        self.wallet = wallet_id(self.label)
        self.funder_id = wallet_id(self.funder)

    def step(self, ts: int, pool: ConstantProductPool, books: Books, clock: Clock) -> None:
        if self._done or ts != self.buy_ts:
            return
        _fund(books, clock, ts, self.funder_id, self.wallet, self.buy_lamports)
        self.sol += self.buy_lamports
        got = _buy(books, clock, ts, pool, self.wallet, self.buy_lamports)
        self.sol -= self.buy_lamports
        self.tokens += got
        self._done = True


@dataclass
class Flipper:
    """Initial buy, then `per_day` full sell+rebuy cycles each day (COIN_MATH §14 row 2)."""

    label: str
    funder: str
    buy_lamports: int
    start_ts: int
    t1: int
    per_day: int = 5
    tokens: int = 0
    sol: int = 0
    _flip_at: set[int] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self.wallet = wallet_id(self.label)
        self.funder_id = wallet_id(self.funder)
        days, rem = divmod(self.t1 - self.start_ts, 86_400)
        if rem:
            days += 1
        interval = 86_400 // self.per_day
        times: set[int] = set()
        for i in range(1, self.per_day * max(days, 1) + 1):
            t = self.start_ts + i * interval
            if t >= self.t1:
                t = self.t1 - 60
            if t > self.start_ts:
                times.add(t)
        self._flip_at = times

    def step(self, ts: int, pool: ConstantProductPool, books: Books, clock: Clock) -> None:
        if ts == self.start_ts and self.tokens == 0 and self.sol == 0:
            # Extra SOL so a later rebuy of the same size always has inventory.
            _fund(books, clock, ts, self.funder_id, self.wallet, self.buy_lamports * 2)
            self.sol += self.buy_lamports * 2
            got = _buy(books, clock, ts, pool, self.wallet, self.buy_lamports)
            self.sol -= self.buy_lamports
            self.tokens += got
            return
        if ts not in self._flip_at or self.tokens <= 0:
            return
        sold = self.tokens
        got_sol = _sell(books, clock, ts, pool, self.wallet, sold)
        self.sol += got_sol
        self.tokens = 0
        got = _buy(books, clock, ts, pool, self.wallet, self.buy_lamports)
        self.sol -= self.buy_lamports
        self.tokens += got


def snapshot_sniper(label: str, funder: str, buy_lamports: int, t1: int) -> Holder:
    """Buys 5 minutes before epoch end (COIN_MATH §14 row 3)."""
    return Holder(label, funder, buy_lamports, buy_ts=t1 - 300)


def whale_splitter(
    funder: str, n: int, buy_lamports: int, buy_ts: int, prefix: str = "split"
) -> list[Holder]:
    """N wallets funded by the same first funder."""
    return [Holder(f"{prefix}-{i}", funder, buy_lamports, buy_ts) for i in range(n)]


def underwater_farmer(label: str, funder: str, buy_lamports: int, buy_ts: int) -> Holder:
    """Buys (typically at a local top) and waits."""
    return Holder(label, funder, buy_lamports, buy_ts)


def pump_group(
    funder: str, n: int, buy_lamports: int, pump_ts: int, prefix: str = "pump"
) -> list[Holder]:
    """Coordinated buys at the same timestamp."""
    return [Holder(f"{prefix}-{i}", funder, buy_lamports, pump_ts) for i in range(n)]
