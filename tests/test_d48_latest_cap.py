"""D48: MC and liquidity use min(window mean, latest reading), so a crash counts at once."""

from adapters.market_data import Sample, aggregate_samples


def _agg(rows):
    return aggregate_samples(rows, 0, 3600 * 12, 300, 3600)


def test_crash_counts_at_once():
    rows = [Sample("m", t * 300, mc_usd=4_400_000.0, liquidity_usd=366_000.0) for t in range(100)]
    rows.append(Sample("m", 100 * 300, mc_usd=440_000.0, liquidity_usd=21_800.0))
    s = _agg(rows)
    assert s.mc_usd == 440_000.0
    assert s.liquidity_usd == 21_800.0


def test_pump_counts_gradually():
    rows = [Sample("m", t * 300, mc_usd=100_000.0, liquidity_usd=50_000.0) for t in range(99)]
    rows.append(Sample("m", 99 * 300, mc_usd=10_000_000.0, liquidity_usd=900_000.0))
    s = _agg(rows)
    assert 100_000.0 < s.mc_usd < 10_000_000.0
    assert s.mc_usd == (99 * 100_000.0 + 10_000_000.0) / 100


def test_missing_readings_are_none():
    s = _agg([Sample("m", 0)])
    assert s.mc_usd is None and s.liquidity_usd is None
