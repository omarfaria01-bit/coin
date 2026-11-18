# GTASP10 index dry run, 18 Nov 2026 (read-only)

Run: `tools/run_index.py --mode rebalance --discover-pages 3 --max-history-pages 3`, `as_of` 2026-11-18T02:00Z,
code commit `aca5679`. `HELIUS_API_KEY` came from the environment; it appears in neither the output file nor the log
(checked with grep). No transaction, no signing, no write outside this report. Cost: 3 Helius parsed-history calls
(30 credits).

## Result: top-10 is EMPTY (0 candidates), and this is a data-source finding, not a bug in the ranking

- The job runs end to end and writes a valid file (`inputs_hash` ae75a938…, `params_hash` 425492e9…, `members: []`).
- Discovery walks the pump.fun program's parsed history. One page is 100 transactions and they span about **1–2 seconds**
  of chain time (blockTime 1794970787–1794970788, 3 distinct slots). 300 transactions contained **0 token creates**.
  pump.fun creates tens of thousands of tokens a day, so walking the program history cannot reach even yesterday's
  launches within a sane credit budget. Raising `--discover-pages` is not a fix.
- Even with candidates, F-filters need 24h of 5-minute samples (`--mode sample` timer). The sample timer is not running
  yet (server install is separate), so every candidate would be `insufficient_data`.

## What is needed for a real top-10 (open question, see issue)

1. A candidate list that is not "walk the whole program": e.g. `--mints-file` seeded from a source kiwi accepts
   (D26 forbids DexScreener `/search` and GMGN scraping, so Claude did not pick one).
2. The 5-minute sample timer running for ≥ 12 h (50% coverage rule) before the first official hour.

Everything else in the pipeline (parse, F4 fee math, filters, weights, hysteresis, emergency check) is covered by the
merged tests (`tests/test_index_*.py`, all green).
