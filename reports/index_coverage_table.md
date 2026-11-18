# GTASP10 index: hours until `min_coverage` (18 Nov 2026)

Issue: [#215](https://github.com/omarfaria01-bit/coin/issues/215). Model: `sim/index_coverage.py`.
Read-only: no network, no RPC, no key, no transaction. Pure expectation, no RNG, so the table is
byte-identical on every run.

Parameters used (from `index/params.json`, not changed): `window_hours` 24, `sample_minutes` 5,
`min_coverage` `1/2`.

## Model

INDEX_RULES §2 counts coverage on **5-minute buckets**: a bucket is filled when at least one
sample lands in it. The sample timer ticks every `sample_minutes` and each tick fills its bucket
unless the sample is missed. For a cadence slower than 5 minutes one tick still fills only one
bucket, so the covered share grows by `(1 - miss_rate) · 5 / interval` per hour of sampling:

- 5-minute cadence, 0% missed: 12 ticks/h → the 144 buckets of a 50% window need 12 h.
- 10-minute cadence: 1 bucket in 2 → at most 50% coverage, and only after the full 24 h.
- 15-minute cadence: 1 bucket in 3 → at most 33%, below the 50% rule.

Coverage stops growing after one full window because the window slides; the ceiling is the same
rate. A ceiling below `min_coverage` means the mint never becomes eligible at that cadence, shown
as `never`.

## Hours until `min_coverage` = 1/2

| sample interval | 0% missed | 10% missed | 30% missed |
|---|---|---|---|
| 5 min | 12.0 h | 13.3 h | 17.1 h |
| 10 min | 24.0 h | never | never |
| 15 min | never | never | never |

## Highest coverage each cadence can hold (why some rows say `never`)

| sample interval | 0% missed | 10% missed | 30% missed |
|---|---|---|---|
| 5 min | 100% | 90% | 70% |
| 10 min | 50% | 45% | 35% |
| 15 min | 33% | 30% | 23% |

## What this means for the live index

- The current job (5-minute sample timer, `coin-index-sample.timer`) clears the 50% gate after
  **12 h** if no sample is missed, **13.3 h** at a 10% miss rate and **17.1 h** at 30%. That
  matches the 18 Nov dry-run note ("the 5-minute sample timer running for ≥ 12 h"), which used the
  zero-miss case.
- With the seed universe from D30 (`index/seed_mints.txt`, aged mints), the first eligible mints
  therefore appear between 12 h and 17 h after the sampler starts, depending on how many samples
  the job actually loses. Coverage is only one gate: F1–F11 also need their data, so the top-10 can
  stay empty after that point for other reasons.
- Do not slow the timer down. At 10 minutes the 50% rule is met only with zero missed samples and
  only after a full day; at 15 minutes it can never be met. A cheaper 10/15-minute timer would buy
  nothing: it makes the index permanently blind, not just slower.
- A mint younger than the 24 h window is measured over its whole life, so it is never slower than
  this table. These hours are the worst case, for mints that already existed when sampling started.

## Limits

- This is an expectation over independent misses. An outage costs exactly the buckets it covers,
  so clustered misses have the same expected count but a wider spread of the eligibility time.
- Coverage is counted on distinct buckets, not on the number of samples; a second sample in the
  same bucket adds nothing.
- `tools/run_index.py` currently passes `sample_seconds = sample_minutes * 60` as the coverage
  bucket width (`adapters/market_data.py`). With the shipped `sample_minutes = 5` this table is
  exact. If the cadence were ever changed, the bucket would have to stay at 5 minutes for this
  table to keep applying; changing that is out of scope here (`index/`/`ops/` untouched) and is
  only flagged as a caveat.

## Reproduce

```
$ uv run python -m sim.index_coverage
| sample interval | 0% missed | 10% missed | 30% missed |
|---|---|---|---|
| 5 min | 12.0 h | 13.3 h | 17.1 h |
| 10 min | 24.0 h | never | never |
| 15 min | never | never | never |

$ uv run python -m sim.index_coverage > /tmp/a && uv run python -m sim.index_coverage > /tmp/b
$ diff /tmp/a /tmp/b && echo identical
identical
```

The module imports only `math` (no clock, no socket); `tests/test_index_coverage.py` asserts that
and checks that this committed table still matches the generator output.
