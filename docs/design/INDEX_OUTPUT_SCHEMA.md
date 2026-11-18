# INDEX_OUTPUT_SCHEMA — JSON output of the hourly index job

For the front end (#164). Read-only data; nothing here moves money.
Producer: `tools/run_index.py` (`index/select.py::run_index` builds the payload,
`tools/index_watch.py` adds `exit_notice` and writes `emergency.json`).
Job: `ops/index-job/index-job.sh hourly`, pushed to branch `index-data`.
This doc is checked by `tests/test_index_output_schema_doc.py`.

## Files on `index-data`

| Path | What |
|---|---|
| `index/out/<YYYY-MM-DDTHH>.json` | Official hourly result (`rebalance_hours = 1`, the production setting). Example `index/out/2026-11-18T03.json`. |
| `index/out/<YYYY-MM-DD>.json` | Same payload when `rebalance_hours` is not 1 (daily name). |
| `index/out/<stamp>.dryrun.json` | Same payload, written when `dry_run` is true (some filters skipped). Not official. |
| `index/out/emergency.json` | Separate small file, see below. Not an index result. |

- The name is the `as_of` time (UTC), cut to the hour (or the day).
- Cadence: one file per hour (systemd timer `coin-index-hourly.timer`). A run
  that fails writes nothing; the previous file stays. Take the newest
  `<stamp>.json` by name (sort the names; ignore `emergency.json`).
- Files are canonical JSON: sorted keys, no spaces, UTF-8.
- If the run is refused or fails there can be gaps in hours. Do not assume
  every hour exists.

## Top-level keys

Required keys are always present. Optional keys appear only in the stated case.

| Key | Type | Req | Meaning |
|---|---|---|---|
| `as_of` | string | yes | Window end, ISO UTC `YYYY-MM-DDTHH:MM:SSZ`. |
| `code_commit` | string | yes | Git SHA of the code that ran, or `"unknown"`. |
| `dry_run` | bool | yes | True when `skipped_filters` is not empty. Treat as not official. |
| `skipped_filters` | list[string] | yes | Filter codes skipped in a dry run, e.g. `["F3"]`. `[]` in an official run. |
| `params_hash` | string | yes | sha256 hex (64) of the params used. |
| `inputs_hash` | string | yes | sha256 hex (64) of candidates, previous members and overrides. |
| `members` | list[object] | yes | The basket, ranked. Can be `[]` when no candidate passes (see below). |
| `excluded` | list[object] | yes | Candidates that did not qualify. Can be `[]`. |
| `changes` | object | yes | `{"entered": [mint], "exited": [{"mint", "reason"}]}`. Both lists can be `[]`. |
| `emergency` | list[object] | yes | Emergency removals applied to this result. Normally `[]`; each item is a string map with a `mint` and a `reason`. |
| `exit_notice` | list[string] | hourly only | Mints that dropped on rank this hour and stay one more hour (exit is deferred 1 h). Present when `rebalance_hours = 1`; absent otherwise. |
| `data_hold` | list[string] | optional | Mints kept this hour with their last passing metrics because the new hour was missing. Absent when nothing was held. |

### `members[]`

| Key | Type | Meaning |
|---|---|---|
| `mint` | string | Token mint, base58. |
| `ticker` | string | Token symbol as reported. |
| `rank` | int | 1 = best. Ranks are 1..n in list order. |
| `log_s` | float | Log score used for ranking and weights. Not a price. |
| `weight_bps` | int | Weight in basis points. Integer, all members sum to exactly 10 000. |
| `metrics` | object | The measured values, see below. |

### `members[].metrics`

Floats are the unit in the name, not base units: `*_usd` = US dollars,
`*_sol` = SOL (not lamports). `null` means not measured. Amounts of tokens are
not in this file. Only `weight_bps` and counts are integers.

`mint`, `ticker`, `name`, `description` (strings), `coverage` (0..1 share of the
window with samples), `age_hours`, `liquidity_usd` and `mc_usd` (window
averages), `top10_pct` (null when F3 is skipped), `total_fees_sol` (lifetime),
`window_fees_sol`, `bundle_pct`, `dev_pct`, `creator_launches_7d` (int),
`mint_authority_revoked`, `freeze_authority_revoked` (bool), `token_program`
(string), `extensions` (list of strings, `[]` for the legacy program),
`unique_traders` (int), `volume_usd` (window total), `independent_traders`
(int), `roundtrip_share` (0..1), `volume_wallets` (int), `median_trade_sol`,
`sources` (map metric name to `"<source>@<ISO time>"`, can be `{}`).

### `excluded[]`

`{"mint": string, "ticker": string, "reason": string}`. `reason` is one of:

- `insufficient_data` — a needed metric is null. The coin may qualify later.
- `weak_keyword` — name match is weak; kiwi can approve it with an allow entry.
- `denied` — on the deny list.
- `F1` .. `F11` — the first filter that failed.

Coins with no keyword match are not listed at all.

### `changes.exited[].reason`

`rank_<n>` (fell to rank n), an `excluded` reason above, or `not_measured`.

### When the basket is empty

`members` is `[]` and `changes.entered` is `[]`. This is normal while most
candidates are `insufficient_data` (as in the real example below). The front
end must show an empty state, not an error. `weight_bps` of an empty basket
sums to 0, not 10 000.

## `emergency.json`

`{"at": "<ISO UTC>", "emergency": [ ... ]}` — written by the emergency check,
same hourly job. Different shape from the files above; do not parse it as an
index result.

## Real example (redacted)

Taken from `origin/index-data:index/out/2026-11-18T03.json`: hashes and commit
shortened, `excluded` cut from 99 to 3 entries. No secret is in these files.

```json
{
  "as_of": "2026-11-18T03:00:00Z",
  "changes": {"entered": [], "exited": []},
  "code_commit": "c6c0ca8d4f91…",
  "dry_run": false,
  "emergency": [],
  "excluded": [
    {"mint": "GLbBjXZ9tQPfALVz44rUW8i7Lx6mmf4XzELCDjfpump", "reason": "weak_keyword", "ticker": "JASON"},
    {"mint": "mpNNwqsXJEK4n7T9t25s4AS88C9xDGXHRpRK9xqpump", "reason": "insufficient_data", "ticker": "GTA"},
    {"mint": "2uQw2gvnhYYQ5T5jJf3MvLPyUquQ54VFHbMHBTtCpump", "reason": "insufficient_data", "ticker": "LEONIDA"}
  ],
  "exit_notice": [],
  "inputs_hash": "…64 hex…",
  "members": [],
  "params_hash": "…64 hex…",
  "skipped_filters": []
}
```

That file has no members, so there is no real `members[]` row to show yet. The
shape of one row is given in the tables above and is asserted by the test
against an offline dry run.
