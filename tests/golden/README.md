# Golden 3-epoch replay

Committed outputs of a fixed, pinned-parameter 3-epoch `run_epoch` run.
See the module docstring in `tests/test_epoch_golden.py` for how float64
scores/shares can move integer payouts by 1 lamport, and how to regenerate:

    UPDATE_GOLDEN=1 uv run pytest tests/test_epoch_golden.py

`epochs/params.json` is the exact `CoinParams` used (defaults are pinned so a
later change such as D15's `unlock_twap_hours` cannot silently drift the
goldens). `epochs/<n>/` is the `adapters.epoch_files` layout. Wallets are
synthetic `sim.agents.wallet_id` labels (`ga`/`gb`/`gc`/`gd`), not real keys.
