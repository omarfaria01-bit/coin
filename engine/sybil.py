"""Evidence graph and clustering (COIN_MATH §7). Owner: Grok, from docs/ENGINE_DESIGN.md §4."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from engine.params import SybilParams
from engine.types import ClusterId, FirstFunding, SolTransfer, TokenEvent, WalletId


class EvidenceKind(StrEnum):
    SAME_FEE_PAYER = "same_fee_payer"
    DIRECT_TRANSFER = "direct_transfer"
    SAME_FIRST_FUNDER = "same_first_funder"
    CO_BUY = "co_buy"
    IDENTICAL_BALANCES = "identical_balances"


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
    raise NotImplementedError


def cluster(
    holders: Iterable[WalletId], evidence: Sequence[Evidence], p: SybilParams
) -> ClusterResult:
    """Union-find on strong edges, then merge weak pairs whose summed evidence ≥ threshold."""
    raise NotImplementedError
