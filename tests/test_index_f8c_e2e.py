"""F8c end to end: fake Helius -> collect facts -> observe Metrics -> F8. Offline (#205)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tests.test_index_collect as base
from adapters.helius_client import HeliusClient
from adapters.index_collect import measure_mints
from index.filters import first_failed_filter
from index.params import FILTER_CODES, IndexParams

ROOT = Path(__file__).resolve().parent.parent
SPL = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
T22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_RAW = json.loads((ROOT / "index" / "params.json").read_text())
# Isolate F8: skip every other filter and the coverage floor, so only F8c can speak.
_RAW["min_coverage"] = "0"
_RAW["dry_run"] = {"skip_filters": [c for c in FILTER_CODES if c != "F8"]}
P = IndexParams.model_validate(_RAW)


def _client(owner: str, extensions: object) -> HeliusClient:
    def send(method: str, url: str, body: dict | None) -> tuple[int, object]:
        if body is not None and body.get("method") == "getAccountInfo":
            info: dict = {"supply": "1000", "decimals": 0}
            info |= {"mintAuthority": None, "freezeAuthority": None}
            if extensions is not None:
                info["extensions"] = extensions
            value = {"owner": owner, "data": {"parsed": {"info": info}}}
            return 200, {"result": {"value": value}}
        return base._send(method, url, body)

    return HeliusClient(
        "unit-test-key",
        send,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        rng=lambda: 0.5,
        rpc_interval=0,
        das_interval=0,
        dex_interval=0,
    )


def _verdict(owner: str, extensions: object) -> str | None:
    row = measure_mints(
        _client(owner, extensions),
        [base.MINT],
        as_of=base.AS_OF,
        window_start=base.AS_OF - 86_400,
        hubs=frozenset(),
        treasury=None,
        samples=[],
        fetched_at="2026-11-18T00:00:00Z",
        sample_seconds=300,
        holder_seconds=3600,
    )[0]
    return first_failed_filter(row, P)


@pytest.mark.parametrize(
    ("owner", "extensions", "expected"),
    [
        (SPL, None, None),  # legacy SPL passes
        (T22, [{"extension": "metadataPointer"}], None),  # allowlisted extension passes
        (T22, [{"extension": "metadataPointer"}, {"extension": "transferHook"}], "F8"),
        (T22, [{"extension": "permanentDelegate"}], "F8"),  # T22 permanentDelegate rejected
        (T22, [{"nope": 1}], "insufficient_data"),  # unreadable entry: unknown, fail-safe
    ],
    ids=["legacy", "metadata-pointer", "transfer-hook", "permanent-delegate", "unreadable"],
)
def test_f8c_through_adapter_path(owner: str, extensions: object, expected: str | None) -> None:
    assert _verdict(owner, extensions) == expected
