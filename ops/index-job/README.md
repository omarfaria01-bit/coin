# GTASP10 index job

Read-only. The script never signs, never sends, and never prints `HELIUS_API_KEY`.
Install on the server is done by the assistant. This repo does not open that machine.

## What runs

- `coin-index-sample.timer` — every 5 minutes, `--mode sample`. It is the only source of samples. It never pulls code and uses its own lock (`$COIN_INDEX_LOCK.sample`), so a slow hourly run does not skip it.
- `coin-index-hourly.timer` — every UTC hour. Pulls `main`, runs `--mode rebalance`, then `--mode emergency`, then pushes `index/out/` to the `index-data` branch. It takes no sample of its own. It holds `$COIN_INDEX_LOCK` (default `/var/lib/coin/index-job.lock`).

"Samples exist" means at least one sample for the mint in the window. There is no coverage minimum (D35); zero samples gives `insufficient_data`.

Membership uses the previous hour's file. The 8/12 rank band applies, and a rank exit waits one extra hour. A member whose hour is missing keeps its last passing metrics. If rebalance or emergency errors, nothing is pushed and the previous remote file stays.

## Env

`/etc/coin/index.env` (mode 600), loaded by the units:

- `HELIUS_API_KEY` (required)
- `COIN_REPO` (default `/opt/coin`)
- `COIN_INDEX_WORKTREE` (default `/var/lib/coin/index-data`)
- `COIN_INDEX_DISCOVER_PAGES` (default `10`)

No DexScreener key. The key is not written to git or to the journal by this script.

## Update after a merge

```bash
cd /opt/coin && git pull --ff-only origin main
sudo systemctl daemon-reload   # only if a unit or timer file changed
```

The script needs no restart; the next tick runs the new version.

## Install

```bash
sudo install -m 755 ops/index-job/index-job.sh /opt/coin/ops/index-job/index-job.sh
sudo cp ops/index-job/coin-index-*.service ops/index-job/coin-index-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now coin-index-sample.timer coin-index-hourly.timer
```

Cron, if systemd timers are not used. Times are UTC:

```
*/5 * * * * /opt/coin/ops/index-job/index-job.sh sample
0 * * * * /opt/coin/ops/index-job/index-job.sh hourly
```

## Dry run by hand

```bash
HELIUS_API_KEY=... uv run python tools/run_index.py \
  --as-of 2026-11-18T19:00:00+00:00 --out index/out --mode rebalance
```

That writes `index/out/2026-11-18T19.json` (or `.dryrun.json` only if `skip_filters` is non-empty). It does not send a transaction.
