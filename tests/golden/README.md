# Golden epoch replay (v0.3.3, #83)

`v033_replay.json` is a 3-epoch fixture run with the committed `config/coin.json`. It covers an S2 cluster, a soft-vesting forfeit, a tainted lot sold to the pool, the price unlock from trusted reserves, a sniper below T_START, and a pending carry that is paid later. `v033/` holds the files that `tools/run_epoch` writes for it.

- Regenerate with `uv run python tools/regen_golden.py`. This is the only supported way. Commit the diff together with the change that caused it.
- Check with `uv run python tools/regen_golden.py --check`, which exits 1 if the goldens are stale.
- `tests/test_golden_v033.py` checks that the output is byte-identical to the goldens, that it is the same under `PYTHONHASHSEED` 0, 1 and 424242, and that the fixture still uses the defaults. Changing any default changes `inputs_hash` and fails the test.
