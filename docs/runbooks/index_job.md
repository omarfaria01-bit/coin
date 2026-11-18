# Runbook: GTASP10 index job (Hetzner)

Read-only job. It never signs or sends, and never prints `HELIUS_API_KEY`.
Files: `ops/index-job/` (script, units, README), `tools/run_index.py`. All times UTC.
Run these commands on the server, in a shell with sudo.

## What runs

| Unit | When | Does |
|---|---|---|
| `coin-index-sample.timer` | every 5 min | `index-job.sh sample` → `--mode sample` |
| `coin-index-hourly.timer` | every UTC hour | sample at hh:59:59, then `--mode rebalance`, `--mode emergency`, push `index/out/` to branch `index-data` |

Both services are `Type=oneshot`. The script takes a lock (`/var/lib/coin/index-job.lock`), so two runs never overlap.

## Env (never print, never commit)

`/etc/coin/index.env`, mode 600, loaded by the script and by the units:

- `HELIUS_API_KEY` — required. Without it the script exits 2.
- `COIN_INDEX_DISCOVER_PAGES` — discovery pages, default `100`.
- Optional: `COIN_REPO` (`/opt/coin`), `COIN_INDEX_WORKTREE` (`/var/lib/coin/index-data`), `COIN_INDEX_MINTS` (seed file path).

Check the file is protected without showing it: `sudo stat -c '%a %U' /etc/coin/index.env` (expect `600 root`).
Do not `cat` it.

## Pull the code

Each run already does `git fetch origin main && git pull --ff-only origin main` in `/opt/coin`.
It refuses to run if the repo is dirty (`repo is dirty; published index left unchanged`).
To pull by hand:

```bash
cd /opt/coin
git status --porcelain          # must print nothing
git fetch origin main && git pull --ff-only origin main
```

If the unit files changed in the PR, copy them again and reload:

```bash
sudo cp ops/index-job/coin-index-*.service ops/index-job/coin-index-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

## Start / stop

```bash
sudo systemctl enable --now coin-index-sample.timer coin-index-hourly.timer   # start
sudo systemctl disable --now coin-index-sample.timer coin-index-hourly.timer  # stop
systemctl list-timers 'coin-index-*'                                          # next / last run
```

Stop one timer only: use the same command with just that timer name.
Stopping a timer does not kill a run already in progress.

## Check the last run

```bash
journalctl -u coin-index-hourly.service -n 50 --no-pager
journalctl -u coin-index-sample.service -n 20 --no-pager
systemctl status coin-index-hourly.service --no-pager
```

Messages you can see:

- `HELIUS_API_KEY is not set` (exit 2) → fix `/etc/coin/index.env`.
- `index job already running` (exit 1) → another run holds the lock; wait.
- `repo is dirty; published index left unchanged` (exit 1) → clean `/opt/coin`, see Rollback.
- `sample failed; older samples kept` → one sample failed, the hour still ran.
- `no index change to publish` → nothing new, normal.
- `push failed; remote index-data left unchanged` → published file did not change. Check network and git access.

Published result: `git fetch origin index-data && git log origin/index-data -5 --oneline`.
Files are `index/out/YYYY-MM-DDTHH.json` (`.dryrun.json` when `skip_filters` is non-empty).

## Empty top-10 = coverage, not a crash

The score window is 24 h of 5-minute buckets. A mint needs samples covering at least `min_coverage`
(`1/2` in `index/params.json`) of that window. Below that it is `insufficient_data` and is not ranked.

So right after a first start, or after the sample timer was stopped, the list can be empty or short
for about 12 hours. Hourly samples alone can never reach 50%. This is expected.

Check before worrying:

1. `systemctl list-timers 'coin-index-sample.timer'` — is it running?
2. `journalctl -u coin-index-sample.service --since "1 hour ago" --no-pager` — any errors?
3. Wait until the sample timer has run about 12 h without gaps, then look at the next hourly file.

If the sample timer ran fine for more than 12 h and the list is still empty, open an issue with the journal lines.
Do not lower `min_coverage` without a DECISIONS.md entry.

## Add mints to the seed file

`index/seed_mints.txt`: one mint per line, `# comment` allowed. A seed is only a mint to measure.
Every filter still applies and `deny` in `index/overrides.json` still wins.
Never put the index coin (`params.self_mint`) in it.

1. Edit the file on a branch in your own checkout (not on the server).
2. Open a PR linked to an issue. After merge, the next run picks it up through `git pull --ff-only`.
3. A new mint has no samples, so it needs about 12 h to pass coverage.

## Rollback

Bad code on main:

1. Stop the timers (see Start / stop).
2. Revert the bad PR on GitHub (a new PR). Do not reset `main` on the server.
3. `cd /opt/coin && git pull --ff-only origin main`, then start the timers.

Dirty repo on the server: `git -C /opt/coin status`, then `git -C /opt/coin stash` to keep the changes. Do not use `reset --hard` without kiwi.

Bad published file on `index-data`: stop the timers, then revert the last commit from the worktree:

```bash
cd /var/lib/coin/index-data
git fetch origin index-data
git checkout --detach origin/index-data
git revert --no-edit HEAD
git push origin HEAD:index-data
```

Start the timers again only after the cause is fixed. The next hourly run rewrites the files from the current rules.
Nothing on-chain is touched by this job, so there is nothing to undo there.
