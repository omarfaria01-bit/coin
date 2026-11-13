"""Interface every launchpad adapter implements (pad unknown until release, COIN_MATH §15)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from engine.params import PadParams
from engine.types import WalletId


class PadAdapter(ABC):
    def __init__(self, pad: PadParams) -> None:
        self.pad = pad

    @abstractmethod
    def pool_accounts(self, mint: str) -> frozenset[WalletId]:
        """Curve/pool vault accounts for `mint` (excluded from ledger; used to classify buys)."""

    @abstractmethod
    def is_pool_program(self, program_id: str) -> bool:
        """True if a swap through this program counts as a pool buy/sell."""

    @abstractmethod
    def creator_fee_claim_instructions(self) -> str:
        """Human-readable claim procedure for RUNBOOK_LAUNCH.md (no signing here)."""
