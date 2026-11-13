"""Copy to adapters/pad_<name>.py on launch day and fill from the pad's public docs."""

from __future__ import annotations

from adapters.pad_base import PadAdapter
from engine.types import WalletId


class TemplatePad(PadAdapter):
    def pool_accounts(self, mint: str) -> frozenset[WalletId]:
        raise NotImplementedError("fill from pad docs")

    def is_pool_program(self, program_id: str) -> bool:
        return program_id in self.pad.program_ids

    def creator_fee_claim_instructions(self) -> str:
        raise NotImplementedError("fill from pad docs")
