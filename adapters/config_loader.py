"""Load and validate config/coin.json and config/pad.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engine.params import CoinParams, PadParams

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_coin(path: Path = CONFIG_DIR / "coin.json") -> CoinParams:
    return CoinParams.model_validate_json(path.read_text())


def load_pad(path: Path = CONFIG_DIR / "pad.json") -> PadParams:
    return PadParams.model_validate_json(path.read_text())


def params_hash(params: CoinParams | PadParams) -> str:
    """sha256 of the canonical JSON (sorted keys), recorded in epochs/<n>/inputs.json."""
    canonical = json.dumps(params.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
