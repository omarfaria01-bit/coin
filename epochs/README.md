# epochs/

Runtime artifacts for one computed epoch, written by `adapters.epoch_files`.
This directory is gitignored except this README. Nothing here is published
or sent to a network.

```python
from pathlib import Path
from adapters.epoch_files import write_epoch, read_epoch

dest = write_epoch(Path("epochs"), result, state, tree)
# dest == Path("epochs/<n>") where n is result.epoch
result, state, tree = read_epoch(dest)
```

Layout of `epochs/<n>/`:

- `result.json` — `EpochResult` as canonical JSON (sorted keys, trailing newline).
  Money fields are ints, never floats.
- `payouts.csv` — `wallet,amount` rows sorted by wallet, trailing newline.
- `tree.json` — merkle root and layers as hex; `root` is `null` when there is no tree.
- `state.json` — `EpochState` to carry into the next epoch, same JSON rules.
- `inputs_hash.txt` — the `inputs_hash` hex from the result, trailing newline.

`write_epoch` refuses to overwrite an existing `epochs/<n>/` whose content would
change. A repeat write of identical bytes is a no-op. Timestamps, if any, come
from the result/state objects; the adapter does not read the clock.
