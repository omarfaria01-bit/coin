"""Sybil clustering, COIN_MATH v0.3.3 §7. Exact weights (Fraction), no floats. Owner: Grok.

Nodes are holders plus the wallets that fund them. Evidence between two wallets is
**strong** (merges alone: S1 co-signed tx, S2 funded buy, S3 manual override) or a
**link** (L1–L6, merges only when the pair's links sum to ≥ 1 and include a two-sided
L1/L2). A shared fee payer is informational only. Hubs' edges are ignored. Clusters are
the connected components (union-find); the cluster id is its smallest holder wallet
(the smallest wallet only if it has no holder), so ids stay holder addresses.
v0.2 ``engine/sybil.py`` stays until #82 wiring switches to this module.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from itertools import combinations

from networkx.utils.union_find import UnionFind

from engine.types import ClusterId, EventKind, SolTransfer, TokenEvent, WalletId

_DAY = 86_400
MERGE_SUM = Fraction(1)
REVIEW_CLUSTER_SIZE = 50  # clusters with more wallets than this go to review
REVIEW_SHARED_PAYER = 5  # a fee payer shared by at least this many holders


class Kind(StrEnum):
    S1_COSIGNED = "s1_cosigned"
    S2_FUNDED_BUY = "s2_funded_buy"
    S3_OVERRIDE = "s3_override"
    L1_TOKEN_BOTH_WAYS = "l1_token_both_ways"
    L2_SOL_BOTH_WAYS = "l2_sol_both_ways"
    L3_TOKEN_ONE_WAY = "l3_token_one_way"
    L4_CO_TRADE = "l4_co_trade"
    L5_IDENTICAL_BALANCES = "l5_identical_balances"
    L6_SHARED_PROCEEDS = "l6_shared_proceeds"


STRONG = frozenset({Kind.S1_COSIGNED, Kind.S2_FUNDED_BUY, Kind.S3_OVERRIDE})
TWO_SIDED = frozenset({Kind.L1_TOKEN_BOTH_WAYS, Kind.L2_SOL_BOTH_WAYS})
WEIGHTS: Mapping[Kind, Fraction] = {
    Kind.L1_TOKEN_BOTH_WAYS: Fraction(3, 5),
    Kind.L2_SOL_BOTH_WAYS: Fraction(1, 2),
    Kind.L3_TOKEN_ONE_WAY: Fraction(3, 10),
    Kind.L4_CO_TRADE: Fraction(2, 5),
    Kind.L5_IDENTICAL_BALANCES: Fraction(3, 10),
    Kind.L6_SHARED_PROCEEDS: Fraction(1, 2),
}


@dataclass(frozen=True, slots=True)
class Edge:
    a: WalletId  # a < b
    b: WalletId
    kind: Kind
    ref: str  # first tx signature (or override id), for review.csv


@dataclass(frozen=True, slots=True)
class Clusters:
    cluster_of: Mapping[WalletId, ClusterId]
    members: Mapping[ClusterId, tuple[WalletId, ...]]
    link_only: tuple[tuple[WalletId, WalletId], ...]  # merges resting only on links (review)
    review: tuple[ClusterId, ...]  # clusters with > REVIEW_CLUSTER_SIZE wallets
    shared_payers: tuple[WalletId, ...]  # informational: fee payer of ≥ 5 holders


def _pair(a: WalletId, b: WalletId) -> tuple[WalletId, WalletId]:
    return (a, b) if a < b else (b, a)


def _add(out: dict[tuple[WalletId, WalletId, Kind], Edge], a: str, b: str, kind: Kind, ref: str):
    lo, hi = _pair(a, b)
    key = (lo, hi, kind)
    if key not in out or ref < out[key].ref:
        out[key] = Edge(lo, hi, kind, ref)


def _order(e: TokenEvent) -> tuple[int, str, int]:
    return (e.slot, e.sig, e.ix)


def s1_cosigned(
    holders: frozenset[WalletId], signers: Mapping[str, frozenset[WalletId]], hubs: frozenset
) -> list[Edge]:
    """S1: two holders signed the same transaction (``signers``: sig → signer set)."""
    out: dict = {}
    for sig in sorted(signers):
        both = sorted(w for w in signers[sig] if w in holders and w not in hubs)
        for a, b in combinations(both, 2):
            _add(out, a, b, Kind.S1_COSIGNED, sig)
    return list(out.values())


def s2_funded_buys(
    events: Sequence[TokenEvent], sols: Sequence[SolTransfer], hubs: frozenset[WalletId]
) -> list[Edge]:
    """S2: at the time of any pool buy by W, X (not a hub) has sent W ≥ 50% of all SOL W
    received from other wallets **and** ≥ 50% of everything W has spent on buys so far.
    Totals, not coin tracing (§7). X may hold no token: it joins W's cluster anyway.
    """
    sol_rows = [(s.ts, s.slot, s.sig, 0, s) for s in sols if s.src != s.dst]
    buy_rows = [
        (e.ts, e.slot, e.sig, 1 + e.ix, e)  # SOL landing in the same second counts first
        for e in events
        if e.kind is EventKind.BUY and e.dst is not None and e.lamports is not None
    ]
    received: dict[WalletId, int] = defaultdict(int)
    from_x: dict[WalletId, dict[WalletId, int]] = defaultdict(lambda: defaultdict(int))
    spent: dict[WalletId, int] = defaultdict(int)
    out: dict = {}
    for row in sorted([*sol_rows, *buy_rows], key=lambda r: r[:4]):
        item = row[4]
        if isinstance(item, SolTransfer):
            received[item.dst] += item.lamports
            if item.src not in hubs:
                from_x[item.dst][item.src] += item.lamports
            continue
        w, lamports = item.dst, item.lamports
        if w is None or lamports is None:  # pragma: no cover - filtered above
            continue
        spent[w] += lamports
        if w in hubs:
            continue
        for x, amt in sorted(from_x[w].items()):
            if 2 * amt >= received[w] and 2 * amt >= spent[w]:
                _add(out, w, x, Kind.S2_FUNDED_BUY, item.sig)
    return list(out.values())


def s3_overrides(pairs: Iterable[tuple[WalletId, WalletId, str]]) -> list[Edge]:
    """S3: manual merges from ``cluster_overrides.json`` as (a, b, override id)."""
    out: dict = {}
    for a, b, ref in pairs:
        if a != b:
            _add(out, a, b, Kind.S3_OVERRIDE, ref)
    return list(out.values())


def transfer_links(
    events: Sequence[TokenEvent], sols: Sequence[SolTransfer], hubs: frozenset[WalletId]
) -> list[Edge]:
    """L1 token both ways, L2 SOL both ways, L3 one-way token on ≥ 2 distinct days."""
    days: dict[tuple[WalletId, WalletId], set[int]] = defaultdict(set)
    first: dict[tuple[WalletId, WalletId], str] = {}
    for e in sorted(events, key=_order):
        if e.kind is EventKind.TRANSFER and e.src and e.dst and e.src != e.dst:
            if e.src in hubs or e.dst in hubs:
                continue
            days[(e.src, e.dst)].add(e.ts // _DAY)
            first.setdefault((e.src, e.dst), e.sig)
    out: dict = {}
    for src, dst in sorted(days):
        if (dst, src) in days:
            _add(out, src, dst, Kind.L1_TOKEN_BOTH_WAYS, min(first[(src, dst)], first[(dst, src)]))
        elif len(days[(src, dst)]) >= 2:
            _add(out, src, dst, Kind.L3_TOKEN_ONE_WAY, first[(src, dst)])
    sol_first: dict[tuple[WalletId, WalletId], str] = {}
    for s in sorted(sols, key=lambda s: (s.slot, s.sig)):
        if s.src != s.dst and s.src not in hubs and s.dst not in hubs:
            sol_first.setdefault((s.src, s.dst), s.sig)
    for src, dst in sorted(sol_first):
        if (dst, src) in sol_first:
            ref = min(sol_first[(src, dst)], sol_first[(dst, src)])
            _add(out, src, dst, Kind.L2_SOL_BOTH_WAYS, ref)
    return list(out.values())


def cluster(
    holders: Iterable[WalletId],
    edges: Sequence[Edge],
    hubs: frozenset[WalletId] = frozenset(),
    events: Sequence[TokenEvent] = (),
) -> Clusters:
    """Merge rule (§7): any strong edge, or links summing to ≥ 1 incl. an L1/L2 signal.

    Nodes are the holders plus every non-hub wallet on a strong edge (e.g. an S2
    funder). ``events`` only feed the informational shared-fee-payer review list.
    """
    holder_set = set(holders) - hubs
    nodes = set(holder_set)
    for e in edges:
        if e.kind in STRONG and e.a not in hubs and e.b not in hubs:
            nodes.update((e.a, e.b))
    uf = UnionFind(sorted(nodes))
    links: dict[tuple[WalletId, WalletId], Fraction] = defaultdict(Fraction)
    sided: set[tuple[WalletId, WalletId]] = set()
    for e in sorted(edges, key=lambda e: (e.a, e.b, e.kind, e.ref)):
        if e.a not in nodes or e.b not in nodes:
            continue
        if e.kind in STRONG:
            uf.union(e.a, e.b)
            continue
        links[(e.a, e.b)] += WEIGHTS[e.kind]
        if e.kind in TWO_SIDED:
            sided.add((e.a, e.b))
    link_only = []
    for pair in sorted(links):
        if links[pair] >= MERGE_SUM and pair in sided:
            if uf[pair[0]] != uf[pair[1]]:
                link_only.append(pair)
            uf.union(*pair)
    groups: dict[WalletId, list[WalletId]] = defaultdict(list)
    for w in sorted(nodes):
        groups[uf[w]].append(w)
    cluster_of: dict[WalletId, ClusterId] = {}
    members: dict[ClusterId, tuple[WalletId, ...]] = {}
    for mems in sorted((tuple(m) for m in groups.values()), key=lambda m: m[0]):
        cid = min((w for w in mems if w in holder_set), default=mems[0])
        members[cid] = mems
        cluster_of.update({w: cid for w in mems})
    members = dict(sorted(members.items()))
    review = tuple(c for c, m in members.items() if len(m) > REVIEW_CLUSTER_SIZE)
    payer_count: dict[WalletId, set[WalletId]] = defaultdict(set)
    for e in events:
        for w in (e.src, e.dst):
            if w is not None and w in nodes and e.fee_payer != w:
                payer_count[e.fee_payer].add(w)
    shared = tuple(sorted(p for p, hs in payer_count.items() if len(hs) >= REVIEW_SHARED_PAYER))
    return Clusters(cluster_of, members, tuple(link_only), review, shared)


# ---------------------------------------------------------------- one-sided links L4–L6

CO_TRADE_SECONDS = 1
CO_TRADE_MIN = 3
SIZE_TOL = Fraction(1, 10)
BALANCE_TOL = Fraction(1, 1000)
L5_MIN_WALLETS = 4
L5_CREATED_WITHIN = _DAY
L6_WINDOW = _DAY
HUB_CANDIDATE_COUNTERPARTIES = 25


def _close(x: int, y: int, tol: Fraction) -> bool:
    """|x − y| ≤ tol · max(x, y), exactly."""
    hi = max(x, y)
    return abs(x - y) <= tol * hi


def l4_co_trades(events: Sequence[TokenEvent], hubs: frozenset[WalletId]) -> list[Edge]:
    """L4: same direction, same second ±1, size within 10%, on ≥ 3 occasions.

    An occasion counts once per trade on each side, so the pair needs ≥ 3 distinct
    trades of A and ≥ 3 distinct trades of B that match the other wallet.
    """
    raw = [
        (e.ts, e.kind, e.dst if e.kind is EventKind.BUY else e.src, e.amount, e.sig)
        for e in events
        if e.kind in (EventKind.BUY, EventKind.SELL)
    ]
    trades = sorted(t for t in raw if t[2] is not None and t[2] not in hubs)
    matched: dict[tuple[WalletId, WalletId], tuple[set[str], set[str], str]] = {}
    for i, (ts, kind, w, amt, sig) in enumerate(trades):
        j = i + 1
        while j < len(trades) and trades[j][0] - ts <= CO_TRADE_SECONDS:
            ts2, kind2, w2, amt2, sig2 = trades[j]
            j += 1
            if kind2 is not kind or w2 == w or not _close(amt, amt2, SIZE_TOL):
                continue
            (a, sa), (b, sb) = sorted(((w, sig), (w2, sig2)))
            sides = matched.setdefault((a, b), (set(), set(), min(sa, sb)))
            sides[0].add(sa)
            sides[1].add(sb)
    out: dict = {}
    for (a, b), (sa, sb, ref) in sorted(matched.items()):
        if min(len(sa), len(sb)) >= CO_TRADE_MIN:
            _add(out, a, b, Kind.L4_CO_TRADE, ref)
    return list(out.values())


def l5_identical_balances(
    balances: Mapping[WalletId, int],
    created: Mapping[WalletId, int],
    hubs: frozenset[WalletId],
) -> list[Edge]:
    """L5: ≥ 4 wallets with balances within ±0.1% that were all created within 24h."""
    rows = sorted(
        (bal, w) for w, bal in balances.items() if bal > 0 and w in created and w not in hubs
    )
    out: dict = {}
    for i, (low, _w) in enumerate(rows):
        near = [w for bal, w in rows[i:] if _close(bal, low, BALANCE_TOL)]
        if len(near) < L5_MIN_WALLETS:
            continue
        by_time = sorted((created[w], w) for w in near)
        for k, (t_first, _wf) in enumerate(by_time):
            group = [w for t, w in by_time[k:] if t - t_first <= L5_CREATED_WITHIN]
            if len(group) >= L5_MIN_WALLETS:
                for a, b in combinations(sorted(group), 2):
                    _add(out, a, b, Kind.L5_IDENTICAL_BALANCES, f"balance~{low}")
    return list(out.values())


def l6_shared_proceeds(
    events: Sequence[TokenEvent], sols: Sequence[SolTransfer], hubs: frozenset[WalletId]
) -> list[Edge]:
    """L6: two sellers each send SOL to the same non-hub destination within 24h after
    one of their sales (the destination is a third wallet, not one of the two)."""
    sales: dict[WalletId, list[int]] = defaultdict(list)
    for e in events:
        if e.kind is EventKind.SELL and e.src is not None and e.src not in hubs:
            sales[e.src].append(e.ts)
    sent_to: dict[WalletId, dict[WalletId, str]] = defaultdict(dict)  # dest → seller → sig
    for s in sorted(sols, key=lambda s: (s.slot, s.sig)):
        after_sale = any(0 <= s.ts - t <= L6_WINDOW for t in sales.get(s.src, ()))
        if after_sale and s.dst not in hubs and s.dst != s.src:
            sent_to[s.dst].setdefault(s.src, s.sig)
    out: dict = {}
    for dest, sellers in sorted(sent_to.items()):
        for a, b in combinations(sorted(w for w in sellers if w != dest), 2):
            _add(out, a, b, Kind.L6_SHARED_PROCEEDS, min(sellers[a], sellers[b]))
    return list(out.values())


def hub_candidates(
    events: Sequence[TokenEvent], sols: Sequence[SolTransfer], hubs: frozenset[WalletId]
) -> tuple[WalletId, ...]:
    """Review list only: wallets with ≥ 25 distinct counterparties. Never automatic (§7)."""
    peers: dict[WalletId, set[WalletId]] = defaultdict(set)
    pairs = [(e.src, e.dst) for e in events if e.kind is EventKind.TRANSFER]
    pairs += [(s.src, s.dst) for s in sols]
    for src, dst in pairs:
        if src is not None and dst is not None and src != dst:
            peers[src].add(dst)
            peers[dst].add(src)
    return tuple(
        sorted(
            w for w, p in peers.items() if w not in hubs and len(p) >= HUB_CANDIDATE_COUNTERPARTIES
        )
    )
