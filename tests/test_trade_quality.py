"""F9/F10 trade quality (#170, D33): per-wallet SOL volume and same-wallet round trips."""

from adapters.market_data import trade_quality

MINT = "MintAAA"
CREATOR = "creator"
SOL = 1_000_000_000
KW = dict(
    window_start=0,
    window_end=10_000,
    truncated=False,
    creator=CREATOR,
    min_trader_lamports=SOL // 20,
    roundtrip_seconds=600,
)


def swap(sig: str, wallet: str, t: int, side: str, lamports: int) -> dict:
    buy = side == "buy"
    move = (
        {"mint": MINT, "from": "curve", "to": wallet, "amount": 5}
        if buy
        else {"mint": MINT, "from": wallet, "to": "curve", "amount": 5}
    )
    return {
        "signature": sig,
        "block_time": t,
        "ok": True,
        "summary": "swap",
        "fee_payer": wallet,
        "transfers": [move],
        "sol_out": lamports if buy else 0,
        "sol_in": 0 if buy else lamports,
    }


def q(txs: list, **over):
    return trade_quality(txs, MINT, **{**KW, **over})


def test_many_tiny_wallets_are_not_independent_traders() -> None:
    txs = [swap(f"s{i}", f"w{i}", 100, "buy", SOL // 100) for i in range(200)]
    got = q(txs)
    assert got is not None and got.independent_traders == 0


def test_volume_boundary_per_wallet_and_creator_excluded() -> None:
    txs = [
        swap("a", "w1", 1, "buy", SOL // 20),  # exactly 0.05 SOL counts
        swap("b", "w2", 1, "buy", SOL // 20 - 1),  # one lamport short
        swap("c", CREATOR, 1, "buy", SOL),  # creator never counts
    ]
    got = q(txs)
    assert got is not None and got.independent_traders == 1


def test_loop_wallet_is_all_roundtrip() -> None:
    txs = []
    for i in range(10):
        txs.append(swap(f"b{i}", "loop", 100 + 20 * i, "buy", SOL))
        txs.append(swap(f"s{i}", "loop", 110 + 20 * i, "sell", SOL))
    got = q(txs)
    assert got is not None
    assert got.roundtrip_share == 1.0 and got.volume_wallets == 0 and got.median_trade_sol is None


def test_roundtrip_window_boundary() -> None:
    inside = q([swap("a", "w", 0, "buy", SOL), swap("b", "w", 600, "sell", SOL)])
    outside = q([swap("a", "w", 0, "buy", SOL), swap("b", "w", 601, "sell", SOL)])
    assert inside is not None and inside.roundtrip_share == 1.0
    assert outside is not None and outside.roundtrip_share == 0.0 and outside.volume_wallets == 1


def test_mixed_flow_of_30_wallets_survives() -> None:
    txs = []
    for i in range(30):
        side = "buy" if i % 2 == 0 else "sell"
        txs.append(swap(f"s{i}", f"w{i}", 100, side, SOL // 10))
    got = q(txs)
    assert got is not None
    assert got.independent_traders == 30 and got.volume_wallets == 30
    assert got.roundtrip_share == 0.0 and got.median_trade_sol == 0.1


def test_partial_roundtrip_keeps_the_remainder() -> None:
    got = q([swap("a", "w", 0, "buy", 3 * SOL), swap("b", "w", 10, "sell", SOL)])
    assert got is not None
    assert got.roundtrip_share == 0.5  # 2 SOL of 4 SOL
    assert got.volume_wallets == 1 and got.median_trade_sol == 2.0


def test_incomplete_or_ambiguous_data_fails_closed() -> None:
    ok = swap("a", "w", 1, "buy", SOL)
    assert q([ok], truncated=True) is None
    assert q([{**ok, "sol_out": None}]) is None
    assert q([{**ok, "fee_payer": None}]) is None
    assert q([{**ok, "transfers": [{"mint": MINT, "from": "x", "to": "y", "amount": 5}]}]) is None
    assert q([{**ok, "block_time": None}]) is None


def test_duplicates_and_out_of_window_are_ignored() -> None:
    a = swap("a", "w", 1, "buy", SOL)
    got = q([a, a, swap("old", "z", -5, "buy", SOL)])
    assert got is not None and got.independent_traders == 1 and got.volume_wallets == 1
