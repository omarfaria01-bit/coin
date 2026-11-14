"""Config files validate against the typed models and match the spec defaults (COIN_MATH v0.2)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapters.config_loader import CONFIG_DIR, load_coin, load_pad, params_hash
from engine.params import CoinParams, DrawParams, FeeParams, TreasuryBotParams

ROOT = Path(__file__).resolve().parent.parent


def test_committed_coin_json_equals_defaults():
    assert load_coin() == CoinParams()


def test_committed_pad_json_is_unfilled_template():
    pad = load_pad()
    assert pad.name is None and pad.vesting_mode is None


def test_spec_defaults():
    p = CoinParams()
    assert p.scoring.cap == 0.05
    assert p.rewards.alpha_per_day == 0.10
    assert (p.fees.dev, p.fees.holder_pot, p.fees.draw_pot, p.fees.buyback_burn) == (
        0.25,
        0.35,
        0.25,
        0.15,
    )
    assert p.draws.prize_split == (0.40,) + (0.10,) * 3 + (0.05,) * 6
    assert p.vesting.unlock_twap_hours == 24.0
    assert p.treasury_bot.mode == "paper"


def test_unknown_keys_rejected():
    raw = json.loads((CONFIG_DIR / "coin.json").read_text())
    raw["surprise"] = 1
    with pytest.raises(ValidationError):
        CoinParams.model_validate(raw)
    raw = json.loads((CONFIG_DIR / "coin.json").read_text())
    raw["fees"]["typo_share"] = 0.0
    with pytest.raises(ValidationError):
        CoinParams.model_validate(raw)


def test_fee_shares_must_sum_to_one():
    with pytest.raises(ValidationError):
        FeeParams(dev=0.3)


def test_prize_split_must_not_exceed_one():
    with pytest.raises(ValidationError):
        DrawParams(prize_split=(0.6, 0.5))


def test_live_mode_cannot_be_committed():
    with pytest.raises(ValidationError):
        TreasuryBotParams(mode="live")


def test_params_hash_is_stable_and_sensitive():
    assert params_hash(CoinParams()) == params_hash(load_coin())
    assert params_hash(CoinParams()) != params_hash(CoinParams(scoring={"cap": 0.04}))


def test_schema_files_up_to_date():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_schema.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
