"""Evidence graph and clustering (COIN_MATH §7). Owner: Grok, from docs/ENGINE_DESIGN.md §4."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from operator import attrgetter

from networkx.utils.union_find import UnionFind

from engine.params import SybilParams
from engine.types import (
    ClusterId,
    EventKind,
    FirstFunding,
    SolTransfer,
    TokenEvent,
    WalletId,
)


class EvidenceKind(StrEnum):
    SAME_FEE_PAYER = "same_fee_payer"
    DIRECT_TRANSFER = "direct_transfer"
    SAME_FIRST_FUNDER = "same_first_funder"
    CO_BUY = "co_buy"
    IDENTICAL_BALANCES = "identical_balances"
    TWO_SIDED_TOKEN = "two_sided_token"  # L1
    TWO_SIDED_SOL = "two_sided_sol"  # L2
    ONE_WAY_TOKEN = "one_way_token"  # L3, ≥ 2 distinct days


@dataclass(frozen=True, slots=True)
class Evidence:
    a: WalletId  # a < b (lexicographic)
    b: WalletId
    kind: EvidenceKind
    weight: float
    ref: str  # tx signature or short description, for review.csv


@dataclass(frozen=True, slots=True)
class ClusterResult:
    cluster_of: Mapping[WalletId, ClusterId]
    members: Mapping[ClusterId, tuple[WalletId, ...]]  # sorted
    confidence: Mapping[ClusterId, float]  # in (0, 1]
    review: tuple[ClusterId, ...]  # clusters with ≥ review_cluster_size wallets, sorted


def _pair(a: WalletId, b: WalletId) -> tuple[WalletId, WalletId]:
    return (a, b) if a < b else (b, a)


def _keep_first(dst: dict[tuple[WalletId, WalletId, EvidenceKind], Evidence], ev: Evidence) -> None:
    key = (ev.a, ev.b, ev.kind)
    prev = dst.get(key)
    if prev is None or ev.ref < prev.ref:
        dst[key] = ev


def _rel_close(x: int, y: int, tol: float) -> bool:
    m = max(x, y)
    return True if m == 0 else abs(x - y) / m <= tol


def _first_buy_ts(events: Sequence[TokenEvent], ok: set[WalletId]) -> dict[WalletId, int]:
    first: dict[WalletId, TokenEvent] = {}
    for e in sorted(events, key=lambda ev: (ev.slot, ev.sig, ev.ix)):
        if e.kind is EventKind.BUY and e.dst in ok and e.dst not in first:
            first[e.dst] = e
    return {w: e.ts for w, e in first.items()}


def _same_fee_payer(events, ok, hubs, weight, dst) -> None:
    groups: dict[WalletId, list[TokenEvent]] = defaultdict(list)
    for e in events:
        if e.fee_payer not in hubs:
            groups[e.fee_payer].append(e)
    for payer, evs in groups.items():
        evs.sort(key=lambda e: (e.slot, e.sig, e.ix))
        appeared: set[WalletId] = set()
        first_sig: str | None = None
        paid_other = False
        for e in evs:
            involved = {w for w in (e.src, e.dst) if w is not None and w in ok}
            if not involved:
                continue
            if first_sig is None:
                first_sig = e.sig
            appeared.update(involved)
            if any(w != payer for w in involved):
                paid_other = True
        if first_sig is None or len(appeared) < 2:
            continue
        if payer in ok and not paid_other:
            continue
        for a, b in combinations(sorted(appeared), 2):
            _keep_first(dst, Evidence(a, b, EvidenceKind.SAME_FEE_PAYER, weight, first_sig))


def _direct_transfers(events, sols, ok, weight, dst) -> None:
    rows: list[tuple[int, str, int, WalletId, WalletId]] = []
    for e in events:
        if e.kind is EventKind.TRANSFER and e.src in ok and e.dst in ok and e.src != e.dst:
            a, b = _pair(e.src, e.dst)
            rows.append((e.slot, e.sig, e.ix, a, b))
    for s in sols:
        if s.src in ok and s.dst in ok and s.src != s.dst:
            a, b = _pair(s.src, s.dst)
            rows.append((s.slot, s.sig, 0, a, b))
    for _slot, sig, _ix, a, b in sorted(rows):
        _keep_first(dst, Evidence(a, b, EvidenceKind.DIRECT_TRANSFER, weight, sig))


def _same_first_funder(fundings, first_buy_ts, ok, hubs, window_s, weight, dst) -> None:
    by_funder: dict[WalletId, list[WalletId]] = defaultdict(list)
    for f in fundings:
        if f.wallet not in ok or f.funder in hubs or f.wallet not in first_buy_ts:
            continue
        dt = first_buy_ts[f.wallet] - f.ts
        if 0 <= dt <= window_s:
            by_funder[f.funder].append(f.wallet)
    for funder, wallets in by_funder.items():
        for a, b in combinations(sorted(set(wallets)), 2):
            _keep_first(dst, Evidence(a, b, EvidenceKind.SAME_FIRST_FUNDER, weight, funder))


def _co_buys(events, ok, slot_tol, size_tol, min_occ, weight, dst) -> None:
    buys = [e for e in events if e.kind is EventKind.BUY and e.dst in ok]
    buys.sort(key=lambda e: (e.slot, e.sig, e.ix))
    slots: dict[tuple[WalletId, WalletId], set[int]] = defaultdict(set)
    first_ref: dict[tuple[WalletId, WalletId], tuple[int, str, int]] = {}
    n = len(buys)
    for i, ei in enumerate(buys):
        k = i + 1
        while k < n and buys[k].slot <= ei.slot + slot_tol:
            ek = buys[k]
            k += 1
            if ek.dst == ei.dst or not _rel_close(ei.amount, ek.amount, size_tol):
                continue
            assert ei.dst is not None and ek.dst is not None
            pair = _pair(ei.dst, ek.dst)
            slots[pair].add(ei.slot)
            evkey = (ei.slot, ei.sig, ei.ix)
            prev = first_ref.get(pair)
            if prev is None or evkey < prev:
                first_ref[pair] = evkey
    for pair, occs in slots.items():
        if len(occs) >= min_occ:
            a, b = pair
            _keep_first(dst, Evidence(a, b, EvidenceKind.CO_BUY, weight, first_ref[pair][1]))


def _identical_balances(
    balances, fundings, ok, min_wallets, bal_tol, created_s, weight
) -> list[Evidence]:
    created: dict[WalletId, int] = {}
    for f in fundings:
        if f.wallet in ok and f.wallet not in created:
            created[f.wallet] = f.created_ts
    rows = sorted((balances[w], created[w], w) for w in ok if w in balances and w in created)
    if len(rows) < min_wallets:
        return []

    kind = EvidenceKind.IDENTICAL_BALANCES
    chunks: list[list[Evidence]] = []

    def emit(group: list[WalletId]) -> None:
        if len(group) < min_wallets:
            return
        g = sorted(group)
        ref = f"group:{g[0]}"
        chunks.append([Evidence(a, b, kind, weight, ref) for a, b in combinations(g, 2)])

    def emit_created(window: list[tuple[int, int, WalletId]]) -> None:
        if len(window) < min_wallets:
            return
        inner = sorted((c, w) for _b, c, w in window)
        l2, m = 0, len(inner)
        for r2 in range(m):
            while inner[r2][0] - inner[l2][0] > created_s:
                l2 += 1
            at_end = r2 == m - 1
            nxt = False if at_end else inner[r2 + 1][0] - inner[l2][0] > created_s
            if at_end or nxt:
                emit([w for _c, w in inner[l2 : r2 + 1]])

    left, n = 0, len(rows)
    for right in range(n):
        while left <= right and not _rel_close(rows[left][0], rows[right][0], bal_tol):
            left += 1
        at_end = right == n - 1
        nxt = False if at_end else not _rel_close(rows[left][0], rows[right + 1][0], bal_tol)
        if (at_end or nxt) and (right - left + 1) >= min_wallets:
            emit_created(rows[left : right + 1])

    if not chunks:
        return []
    if len(chunks) == 1:
        return chunks[0]  # combinations of a sorted group is already (a, b, kind, ref) order
    acc: dict[tuple[WalletId, WalletId], Evidence] = {}
    for chunk in chunks:
        for ev in chunk:
            prev = acc.get((ev.a, ev.b))
            if prev is None or ev.ref < prev.ref:
                acc[ev.a, ev.b] = ev
    return sorted(acc.values(), key=attrgetter("a", "b", "kind", "ref"))


def build_evidence(
    holders: Iterable[WalletId],
    events: Sequence[TokenEvent],
    sol_transfers: Sequence[SolTransfer],
    fundings: Sequence[FirstFunding],
    balances_at_epoch_end: Mapping[WalletId, int],
    hubs: frozenset[WalletId],
    p: SybilParams,
) -> list[Evidence]:
    """Turn raw data into evidence edges between holders. Hubs never create edges."""
    ok = {w for w in holders if w not in hubs}
    dst: dict[tuple[WalletId, WalletId, EvidenceKind], Evidence] = {}
    w = p.weights
    _same_fee_payer(events, ok, hubs, w.same_fee_payer, dst)
    _direct_transfers(events, sol_transfers, ok, w.direct_transfer, dst)
    _same_first_funder(
        fundings,
        _first_buy_ts(events, ok),
        ok,
        hubs,
        p.funder_window_hours * 3600.0,
        w.same_first_funder,
        dst,
    )
    _co_buys(
        events,
        ok,
        p.co_buy_slot_tolerance,
        p.co_buy_size_tolerance,
        p.co_buy_min_occurrences,
        w.co_buy,
        dst,
    )
    ib = _identical_balances(
        balances_at_epoch_end,
        fundings,
        ok,
        p.identical_balance_min_wallets,
        p.identical_balance_tolerance,
        p.identical_balance_created_within_hours * 3600.0,
        w.identical_balances,
    )
    if not dst:
        return ib
    for ev in ib:
        _keep_first(dst, ev)
    return sorted(dst.values(), key=attrgetter("a", "b", "kind", "ref"))


def cluster(
    holders: Iterable[WalletId], evidence: Sequence[Evidence], p: SybilParams
) -> ClusterResult:
    """Union-find on strong edges, then merge weak pairs whose summed evidence ≥ threshold."""
    holder_list = sorted(set(holders))
    uf = UnionFind(holder_list)
    pair_sum: dict[tuple[WalletId, WalletId], float] = defaultdict(float)
    for ev in evidence:
        pair_sum[(ev.a, ev.b)] += ev.weight
    comp_conf: dict[WalletId, float] = {}

    def _union(a: WalletId, b: WalletId) -> None:
        if a not in uf.parents or b not in uf.parents or uf[a] == uf[b]:
            return
        ra, rb = uf[a], uf[b]
        score = min(1.0, pair_sum[_pair(a, b)])
        new_min = min(comp_conf.get(ra, 1.0), comp_conf.get(rb, 1.0), score)
        uf.union(a, b)
        comp_conf[uf[a]] = new_min

    for ev in sorted(evidence, key=lambda e: (e.a, e.b, e.kind, e.ref)):
        if ev.weight >= p.strong_edge:
            _union(ev.a, ev.b)
    for a, b in sorted(pair_sum):
        if pair_sum[(a, b)] >= p.merge_threshold:
            _union(a, b)

    groups: dict[WalletId, list[WalletId]] = defaultdict(list)
    for w in holder_list:
        groups[uf[w]].append(w)
    cluster_of: dict[WalletId, ClusterId] = {}
    members: dict[ClusterId, tuple[WalletId, ...]] = {}
    confidence: dict[ClusterId, float] = {}
    for mems in sorted((tuple(sorted(m)) for m in groups.values()), key=lambda t: t[0]):
        cid: ClusterId = mems[0]
        members[cid] = mems
        for w in mems:
            cluster_of[w] = cid
        confidence[cid] = 1.0 if len(mems) == 1 else comp_conf[uf[cid]]
    review = tuple(sorted(c for c, m in members.items() if len(m) >= p.review_cluster_size))
    return ClusterResult(cluster_of, members, confidence, review)


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §7, first slice: fee payer is informational, one-way
# transfers do not merge, link-only merges need an L1 or L2 signal.
# Keep build_evidence / cluster (v0.2) above unchanged until epoch is rewired.
# ---------------------------------------------------------------------------

_DAY = 86_400
L1_WEIGHT = 0.6
L2_WEIGHT = 0.5
L3_WEIGHT = 0.3
TWO_SIDED_KINDS = frozenset({EvidenceKind.TWO_SIDED_TOKEN, EvidenceKind.TWO_SIDED_SOL})
INFORMATIONAL_KINDS = frozenset({EvidenceKind.SAME_FEE_PAYER})


def _transfer_links_v033(
    events: Sequence[TokenEvent],
    sols: Sequence[SolTransfer],
    ok: set[WalletId],
    dst: dict[tuple[WalletId, WalletId, EvidenceKind], Evidence],
) -> None:
    token_days: dict[tuple[WalletId, WalletId], set[int]] = defaultdict(set)
    token_sig: dict[tuple[WalletId, WalletId], str] = {}
    token_rows: list[tuple[int, str, int, WalletId, WalletId, int]] = []
    for e in events:
        if e.kind is EventKind.TRANSFER and e.src in ok and e.dst in ok and e.src != e.dst:
            token_rows.append((e.slot, e.sig, e.ix, e.src, e.dst, e.ts))
    for _slot, sig, _ix, src, dst_w, ts in sorted(token_rows):
        key = (src, dst_w)
        token_days[key].add(ts // _DAY)
        if key not in token_sig:
            token_sig[key] = sig
    token_pairs = {_pair(src, dst_w) for src, dst_w in token_days}
    for a, b in token_pairs:
        ab, ba = (a, b) in token_days, (b, a) in token_days
        if ab and ba:
            ref = min(token_sig[(a, b)], token_sig[(b, a)])
            _keep_first(dst, Evidence(a, b, EvidenceKind.TWO_SIDED_TOKEN, L1_WEIGHT, ref))
            continue
        src, dst_w = (a, b) if ab else (b, a)
        if len(token_days[(src, dst_w)]) >= 2:
            _keep_first(
                dst, Evidence(a, b, EvidenceKind.ONE_WAY_TOKEN, L3_WEIGHT, token_sig[(src, dst_w)])
            )

    sol_sig: dict[tuple[WalletId, WalletId], str] = {}
    sol_rows = [
        (s.slot, s.sig, s.src, s.dst)
        for s in sols
        if s.src in ok and s.dst in ok and s.src != s.dst
    ]
    for _slot, sig, src, dst_w in sorted(sol_rows):
        key = (src, dst_w)
        if key not in sol_sig:
            sol_sig[key] = sig
    sol_pairs = {_pair(src, dst_w) for src, dst_w in sol_sig}
    for a, b in sol_pairs:
        if (a, b) in sol_sig and (b, a) in sol_sig:
            ref = min(sol_sig[(a, b)], sol_sig[(b, a)])
            _keep_first(dst, Evidence(a, b, EvidenceKind.TWO_SIDED_SOL, L2_WEIGHT, ref))


def build_evidence_v033(
    holders: Iterable[WalletId],
    events: Sequence[TokenEvent],
    sol_transfers: Sequence[SolTransfer],
    fundings: Sequence[FirstFunding],
    balances_at_epoch_end: Mapping[WalletId, int],
    hubs: frozenset[WalletId],
    p: SybilParams,
) -> list[Evidence]:
    """v0.3.3 evidence. Fee payer is recorded; transfers use L1/L2/L3."""
    ok = {w for w in holders if w not in hubs}
    dst: dict[tuple[WalletId, WalletId, EvidenceKind], Evidence] = {}
    w = p.weights
    _same_fee_payer(events, ok, hubs, w.same_fee_payer, dst)
    _transfer_links_v033(events, sol_transfers, ok, dst)
    _same_first_funder(
        fundings,
        _first_buy_ts(events, ok),
        ok,
        hubs,
        p.funder_window_hours * 3600.0,
        w.same_first_funder,
        dst,
    )
    _co_buys(
        events,
        ok,
        p.co_buy_slot_tolerance,
        p.co_buy_size_tolerance,
        p.co_buy_min_occurrences,
        w.co_buy,
        dst,
    )
    ib = _identical_balances(
        balances_at_epoch_end,
        fundings,
        ok,
        p.identical_balance_min_wallets,
        p.identical_balance_tolerance,
        p.identical_balance_created_within_hours * 3600.0,
        w.identical_balances,
    )
    for ev in ib:
        _keep_first(dst, ev)
    return sorted(dst.values(), key=attrgetter("a", "b", "kind", "ref"))


def cluster_v033(
    holders: Iterable[WalletId], evidence: Sequence[Evidence], p: SybilParams
) -> ClusterResult:
    """Strong edges merge immediately. Link-only merges need Σ ≥ 1 and an L1/L2 signal.

    SAME_FEE_PAYER is informational: it never contributes to a merge.
    """
    holder_list = sorted(set(holders))
    uf = UnionFind(holder_list)
    link_sum: dict[tuple[WalletId, WalletId], float] = defaultdict(float)
    two_sided: set[tuple[WalletId, WalletId]] = set()
    pair_score: dict[tuple[WalletId, WalletId], float] = defaultdict(float)
    for ev in evidence:
        if ev.kind in INFORMATIONAL_KINDS:
            continue
        pair = (ev.a, ev.b)
        pair_score[pair] += ev.weight
        if ev.kind in TWO_SIDED_KINDS:
            two_sided.add(pair)
            link_sum[pair] += ev.weight
        elif ev.weight < p.strong_edge:
            link_sum[pair] += ev.weight

    comp_conf: dict[WalletId, float] = {}

    def _union(a: WalletId, b: WalletId) -> None:
        if a not in uf.parents or b not in uf.parents or uf[a] == uf[b]:
            return
        ra, rb = uf[a], uf[b]
        score = min(1.0, pair_score[_pair(a, b)])
        new_min = min(comp_conf.get(ra, 1.0), comp_conf.get(rb, 1.0), score)
        uf.union(a, b)
        comp_conf[uf[a]] = new_min

    for ev in sorted(evidence, key=lambda e: (e.a, e.b, e.kind, e.ref)):
        if ev.kind in INFORMATIONAL_KINDS or ev.kind in TWO_SIDED_KINDS:
            continue
        if ev.kind is EvidenceKind.ONE_WAY_TOKEN:
            continue
        if ev.weight >= p.strong_edge:
            _union(ev.a, ev.b)
    for a, b in sorted(link_sum):
        if link_sum[(a, b)] >= p.merge_threshold and (a, b) in two_sided:
            _union(a, b)

    groups: dict[WalletId, list[WalletId]] = defaultdict(list)
    for w in holder_list:
        groups[uf[w]].append(w)
    cluster_of: dict[WalletId, ClusterId] = {}
    members: dict[ClusterId, tuple[WalletId, ...]] = {}
    confidence: dict[ClusterId, float] = {}
    for mems in sorted((tuple(sorted(m)) for m in groups.values()), key=lambda t: t[0]):
        cid: ClusterId = mems[0]
        members[cid] = mems
        for w in mems:
            cluster_of[w] = cid
        confidence[cid] = 1.0 if len(mems) == 1 else comp_conf[uf[cid]]
    review = tuple(sorted(c for c, m in members.items() if len(m) >= p.review_cluster_size))
    return ClusterResult(cluster_of, members, confidence, review)
