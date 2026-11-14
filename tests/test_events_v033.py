"""Tests for engine/events.py: event order, block-time clock, canonical JSON (COIN_MATH §0)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.events import (
    OrderedEvent,
    SlotTime,
    canonical_json,
    clamp_block_times,
    event_order_key,
    sha256_hex,
    sort_events,
)


@dataclass(frozen=True, slots=True)
class _Ev:
    slot: int
    tx_index: int
    ix_index: int
    label: str


def test_event_order_key_and_sort_events() -> None:
    e = _Ev(5, 2, 1, "x")
    assert isinstance(e, OrderedEvent)
    assert event_order_key(e) == (5, 2, 1)
    a, b, c, d = _Ev(1, 0, 1, "a"), _Ev(1, 0, 0, "b"), _Ev(1, 1, 0, "c"), _Ev(0, 5, 5, "d")
    assert [ev.label for ev in sort_events([a, b, c, d])] == ["d", "b", "a", "c"]


@given(
    st.lists(
        st.tuples(
            st.integers(0, 50), st.integers(0, 50), st.integers(0, 50), st.integers(0, 10_000)
        ),
        min_size=0,
        max_size=30,
    )
)
def test_sort_events_is_idempotent_and_matches_python_sort(
    rows: list[tuple[int, int, int, int]],
) -> None:
    events = [_Ev(slot, tx, ix, str(uid)) for slot, tx, ix, uid in rows]
    expected = sorted(events, key=lambda e: (e.slot, e.tx_index, e.ix_index))
    got = sort_events(events)
    assert list(got) == expected
    assert sort_events(got) == got


def test_clamp_block_times_examples() -> None:
    assert clamp_block_times([]) == {}
    # missing block time -> previous slot's value
    assert clamp_block_times([SlotTime(1, 100), SlotTime(2, None), SlotTime(3, 105)]) == {
        1: 100,
        2: 100,
        3: 105,
    }
    # decreasing block time (went backward on-chain) -> clamp forward
    assert clamp_block_times([SlotTime(10, 500), SlotTime(11, 499), SlotTime(12, 600)]) == {
        10: 500,
        11: 500,
        12: 600,
    }
    with pytest.raises(ValueError, match="strictly increasing"):
        clamp_block_times([SlotTime(5, 1), SlotTime(5, 2)])
    with pytest.raises(ValueError, match="strictly increasing"):
        clamp_block_times([SlotTime(5, 1), SlotTime(4, 2)])
    with pytest.raises(ValueError, match="no earlier slot"):
        clamp_block_times([SlotTime(1, None), SlotTime(2, 10)])


@given(
    st.integers(0, 1000),
    st.lists(
        st.tuples(st.integers(1, 20), st.one_of(st.none(), st.integers(0, 2000))),
        min_size=1,
        max_size=20,
    ),
)
def test_clamp_block_times_is_monotone_and_only_uses_given_or_previous_value(
    first_slot: int, deltas: list[tuple[int, int | None]]
) -> None:
    slot = first_slot
    rows: list[SlotTime] = []
    for i, (gap, bt) in enumerate(deltas):
        slot += gap
        if i == 0 and bt is None:
            bt = 100  # the first slot must have a time to clamp from
        rows.append(SlotTime(slot, bt))
    out = clamp_block_times(rows)

    prev_ts = None
    for st_ in rows:
        ts = out[st_.slot]
        if prev_ts is not None:
            assert ts >= prev_ts  # time never moves backward
        if st_.block_time is not None and (prev_ts is None or st_.block_time >= prev_ts):
            assert ts == st_.block_time  # own value used when it isn't a regression
        else:
            assert ts == prev_ts  # missing or decreasing -> clamped to the previous slot
        prev_ts = ts


def test_canonical_json_encoding_rules() -> None:
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":"2","b":"1"}'  # sorted, no whitespace
    out = canonical_json({"n": 10**20, "flag": True, "neg": -3})
    assert json.loads(out) == {"n": str(10**20), "flag": True, "neg": "-3"}
    assert canonical_json([b"\x00\xff", 1]) == b'["00ff","1"]'
    with pytest.raises(TypeError, match="float"):
        canonical_json({"x": 1.5})
    with pytest.raises(TypeError, match="string keys"):
        canonical_json({1: "x"})


def test_sha256_hex_matches_hashlib_over_canonical_bytes() -> None:
    value = {"wallet": "abc", "amount": 7}
    assert sha256_hex(value) == hashlib.sha256(canonical_json(value)).hexdigest()


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=5, alphabet="abcXYZ"),
        st.integers(-(10**9), 10**9),
        min_size=0,
        max_size=6,
    )
)
@settings(max_examples=50)
def test_canonical_json_is_independent_of_dict_insertion_order(d: dict[str, int]) -> None:
    reordered = dict(reversed(list(d.items())))
    assert canonical_json(d) == canonical_json(reordered)
