"""Pure index measurements. Recorded dicts only; no network (#161)."""

from __future__ import annotations

from adapters.market_data import (
    FeeTotals,
    Sample,
    aggregate_samples,
    authorities_revoked,
    bundle_pct,
    creator_launches,
    fee_totals,
    market_cap_usd,
    pick_pair,
    top10_pct,
)

MINT = "Mint111111111111111111111111111111111111111"
ALICE = "Alice11111111111111111111111111111111111111"
BOB = "Bob1111111111111111111111111111111111111111"
CURVE = "Curve111111111111111111111111111111111111111"


def _swap(
    sig: str, when: int, fee: int, tips: int = 0, payer: str = ALICE, ok: bool = True
) -> dict:
    return {
        "signature": sig,
        "slot": 10,
        "block_time": when,
        "ok": ok,
        "fee": fee,
        "tips": tips,
        "fee_payer": payer,
        "summary": "swap",
        "transfers": [{"mint": MINT, "from": CURVE, "to": payer, "amount": 5}],
        "creates": [],
    }


def test_f4_fee_is_base_plus_priority_plus_tip_once() -> None:
    # parsed.fee already includes the priority fee. The tip is separate.
    txs = [
        _swap("a", 100, fee=2_005_000, tips=1_000_000),
        _swap("a", 100, fee=2_005_000, tips=1_000_000),  # same signature
        _swap("b", 500, fee=5_000, payer=BOB),  # outside the window
        {**_swap("c", 120, fee=5_000), "summary": "transfer"},
        {**_swap("d", 120, fee=5_000), "ok": False},
    ]
    got = fee_totals(txs, MINT, window_start=0, window_end=200, truncated=False)
    assert got == FeeTotals(3_010_000, 3_005_000, frozenset({ALICE}))
    assert got.total_fees_sol == 0.003010000
    assert got.window_fees_sol == 0.003005000


def test_f4_truncated_or_missing_fee_stays_none() -> None:
    blank = fee_totals([_swap("a", 1, 5_000)], MINT, window_start=0, window_end=10, truncated=True)
    assert blank.total_fees_sol is None and blank.window_fees_sol is None
    broken = dict(_swap("a", 1, 5_000))
    broken["fee"] = None
    missed = fee_totals([broken], MINT, window_start=0, window_end=10, truncated=False)
    assert missed.lifetime_lamports is None


def test_top10_excludes_vaults_and_unknown_owner_fails_closed() -> None:
    holders = [(CURVE, 800), (ALICE, 100), (BOB, 50), ("Carol", 25)]
    assert top10_pct(holders, 1_000, {CURVE}) == 17.5
    assert top10_pct([("hub", 10), (None, 1)], 100, set()) is None
    assert top10_pct([(ALICE, 10)], 0, set()) is None


def test_bundle_two_wallets_one_wallet_and_unknown() -> None:
    txs = [
        {
            "slot": 7,
            "transfers": [
                {"mint": MINT, "to": CURVE, "amount": 800},
                {"mint": MINT, "to": ALICE, "amount": 50},
                {"mint": MINT, "to": BOB, "amount": 50},
            ],
        }
    ]
    assert bundle_pct(txs, MINT, 1_000, {CURVE}) == 10.0
    assert (
        bundle_pct(
            [{"slot": 7, "transfers": [{"mint": MINT, "to": ALICE, "amount": 50}]}],
            MINT,
            1_000,
            set(),
        )
        == 0.0
    )
    unknown = {
        "slot": 7,
        "transfers": [
            {"mint": MINT, "to": None, "amount": 50},
            {"mint": MINT, "to": BOB, "amount": 1},
        ],
    }
    assert bundle_pct([unknown], MINT, 1_000, set()) is None


def test_creator_launches_are_distinct_mints() -> None:
    rows = [
        {"creator": ALICE, "mint": "a", "block_time": 10},
        {"creator": ALICE, "mint": "a", "block_time": 11},
        {"creator": ALICE, "mint": "b", "block_time": 12},
        {"creator": ALICE, "mint": "c", "block_time": 100},
        {"creator": BOB, "mint": "d", "block_time": 12},
    ]
    assert creator_launches(rows, ALICE, 0, 20, truncated=False) == 2
    assert creator_launches(rows, ALICE, 0, 20, truncated=True) is None
    assert creator_launches(rows, None, 0, 20, truncated=False) is None


def test_aggregate_mean_median_coverage_and_latest_volume() -> None:
    samples = [
        Sample(MINT, t=100, mc_usd=100.0, liquidity_usd=10.0, volume_usd=5.0, top10_pct=10.0),
        Sample(MINT, t=200, mc_usd=300.0, liquidity_usd=30.0, volume_usd=9.0, top10_pct=30.0),
        Sample(MINT, t=3_000, mc_usd=9_999.0),
    ]
    got = aggregate_samples(samples, 0, 1_000, sample_seconds=200, holder_seconds=150)
    assert got.coverage == 0.4
    assert (got.mc_usd, got.liquidity_usd, got.volume_usd, got.top10_pct) == (
        200.0,
        20.0,
        9.0,
        20.0,
    )
    assert aggregate_samples([], 0, 1_000, 200, 1_000).mc_usd is None


def test_authorities_price_and_deepest_pair() -> None:
    assert authorities_revoked({"mintAuthority": None, "freezeAuthority": None}) == (True, True)
    assert authorities_revoked({"mintAuthority": ALICE, "freezeAuthority": None}) == (False, True)
    assert authorities_revoked({}) == (None, None)
    assert market_cap_usd(2.0, 1_500_000, 6) == 3.0
    assert market_cap_usd(float("nan"), 1, 0) is None
    pair = pick_pair(
        [
            {"baseToken": {"address": MINT}, "liquidity": {"usd": 1}, "volume": {"h24": 4}},
            {"baseToken": {"address": MINT}, "liquidity": {"usd": 50}, "volume": {"h24": 8}},
            {"baseToken": {"address": "other"}, "liquidity": {"usd": 999}},
        ],
        MINT,
    )
    assert pair is not None and pair["volume"]["h24"] == 8  # type: ignore[index]
