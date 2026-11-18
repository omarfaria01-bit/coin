# GTASP10 index job

Read-only. The script never signs, never sends, and never prints `HELIUS_API_KEY`.
Install on the server is done by the assistant. This repo does not open that machine.

## What runs

- `coin-index-sample.timer` — every 5 minutes, `--mode sample`. Uses its own separate sampler lock (`$LOCK.sample`), so it runs independently without waiting for the hourly run. The score window is 24 hours of 5-minute buckets.
- `coin-index-hourly.timer` — every UTC hour. Runs `--mode rebalance`, then `--mode emergency`, then pushes `index/out/` to the `index-data` branch. Hourly no longer runs a sample pass (the 5-minute timer owns sampling).

Membership uses the previous hour's file. The 8/12 rank band applies, and a rank exit waits one extra hour. A member whose hour is missing keeps its last passing metrics. If rebalance or emergency errors, nothing is pushed and the previous remote file stays.

## Env

`/etc/coin/index.env` (mode 600), loaded by the units:

- `HELIUS_API_KEY` (required)
- `COIN_REPO` (default `/opt/coin`)
- `COIN_INDEX_WORKTREE` (default `/var/lib/coin/index-data`)
- `COIN_INDEX_ENV` (default `/etc/coin/index.env`)
- `COIN_INDEX_LOCK` (default `/var/lib/coin/index-job.lock`, with sampler using `$LOCK.sample`)
- `COIN_INDEX_MINTS` (default `$COIN_REPO/index/seed_mints.txt`)
- `COIN_INDEX_DISCOVER_PAGES` (default `10`)

No DexScreener key. The key is not written to git or to the journal by this script.

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
