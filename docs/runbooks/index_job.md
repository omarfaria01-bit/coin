# GTASP10 index job — Hetzner runbook

Read-only GTASP10 index on the Hetzner box. Commands match `ops/index-job/`
(units, `index-job.sh`) and `tools/run_index.py`. It never signs, sends, or
prints `HELIUS_API_KEY`, and only writes `index/out/` on `index-data`.

| What | Default |
|---|---|
| Repo, pulled by every run | `/opt/coin` (`COIN_REPO`) |
| Published worktree, branch `index-data` | `/var/lib/coin/index-data` (`COIN_INDEX_WORKTREE`) |
| Env file, mode 600 | `/etc/coin/index.env` (`COIN_INDEX_ENV`) |
| Lock | `/var/lib/coin/index-job.lock` (`COIN_INDEX_LOCK`) |
| Sampler lock | `/var/lib/coin/index-job.lock.sample` (`COIN_INDEX_LOCK.sample`) |
| 5-minute sampler | `coin-index-sample.timer` |
| Hourly build | `coin-index-hourly.timer` |

Both units are `Type=oneshot`, run as root, and load `/etc/coin/index.env`;
`INDEX_RULES.md` has the rules, and this repo does not log in to the server.

## 1. Pull code

```bash
cd /opt/coin
sudo git status --porcelain          # must print nothing
sudo git fetch origin main
sudo git pull --ff-only origin main
sudo systemctl daemon-reload         # only if unit files changed (the script itself needs no restart)
```

`index-job.sh` runs the same pull before every tick and refuses a dirty tree
(`repo is dirty; published index left unchanged`, exit 1). Edit on a branch and
open a PR; never edit files in `/opt/coin`.

## 2. Timers

```bash
sudo systemctl status coin-index-sample.timer coin-index-hourly.timer
sudo systemctl list-timers --all 'coin-index-*'
sudo systemctl stop coin-index-sample.timer coin-index-hourly.timer
sudo systemctl start coin-index-sample.timer coin-index-hourly.timer
sudo systemctl disable --now coin-index-sample.timer coin-index-hourly.timer
sudo systemctl enable --now coin-index-sample.timer coin-index-hourly.timer
sudo systemctl start coin-index-hourly.service  # one tick by hand
```

Stop the job now with `sudo systemctl stop coin-index-sample.service
coin-index-hourly.service`; stopping a timer alone does not stop an in-flight run.

The 5-minute sampler (`coin-index-sample.timer`) uses its own separate sampler lock (`$COIN_INDEX_LOCK.sample`) and runs independently every 5 minutes without waiting for the hourly run. The hourly run runs `--mode rebalance`, then `--mode emergency`, then pushes `index/out/` to `index-data` if it changed; it no longer repeats a sample pass. Keep the sample timer running: a 24 h window has 288 five-minute buckets.

## 3. Check the last run

```bash
sudo journalctl -u coin-index-hourly.service -u coin-index-sample.service \
  --since '26 hours ago' --no-pager
sudo systemctl show -p Result -p ExecMainStatus coin-index-hourly.service
```

A healthy hourly log has `helius_requests ...`, a git line `index <UTC stamp>`,
and the unit ends `Deactivated successfully`. Exit codes: `0` ok, `1` already
running / dirty tree / push failed / run failed, `2` missing key or bad mode,
`3` official-run refusal.

Read the published file (never edit it by hand):

```bash
sudo jq '{as_of, dry_run, members:(.members|length), excluded:(.excluded|length)}' \
  "$(sudo ls -1t /var/lib/coin/index-data/index/out/*.json | grep -v emergency.json | head -1)"
```

`emergency.json` is only the last emergency check; the newest other `*.json` is
the live index.

## 4. Empty top-10

`members: []` is a valid output. Check the reason before touching anything.

1. **Coverage (usual cause).** An `excluded` reason of `insufficient_data` means zero samples were found in the 24h scoring window (no coverage minimum under D35; any samples in the window count). Keep `coin-index-sample.timer` running:
   ```bash
   sudo ls -lt /opt/coin/data/index/samples | head
   sudo wc -l /opt/coin/data/index/samples/*.jsonl | tail -1
   ```
2. **No candidates.** If `excluded` is also empty, discovery found nothing. Seed
   mints (section 5) are the intended source; raising `COIN_INDEX_DISCOVER_PAGES`
   (default `10`) is not a fix by itself.
3. **Other reasons.** `F1`…`F11`, and `denied` are real filter
   results (`INDEX_RULES.md` §3); `dry_run: true` is never an official index.

## 5. Add mints to the seed file

`index/seed_mints.txt` lists mints to measure, one base58 mint per line; `#`
starts a comment and blank lines are ignored. Every filter still applies, and `deny` in `index/overrides.json` still wins. Never put
`params.self_mint` (the index coin) in it. Add lines on a branch and open a PR:
the next hourly run picks the merged file up with `git pull --ff-only`, while a
hot edit in `/opt/coin` makes the tree dirty and stops publishing. Verify with:

```bash
grep -n '<mint>' /opt/coin/index/seed_mints.txt
```

`deny` in `index/overrides.json` needs a reason and kiwi's approval.

## 6. Rollback

**A bad published index.** Revert the data commit; do not edit the worktree.

```bash
sudo git -C /var/lib/coin/index-data log --oneline -10
sudo git -C /var/lib/coin/index-data revert --no-edit <bad-sha>
sudo git -C /var/lib/coin/index-data push origin HEAD:index-data
```

The next hourly run does `reset --hard origin/index-data`, so the revert sticks.
A failed rebalance/emergency run never publishes; the previous remote file stays.

**A bad code deploy on `main`.** Stop the timers first: every run pulls
`origin/main` and would undo a local checkout.

```bash
sudo systemctl disable --now coin-index-sample.timer coin-index-hourly.timer
sudo systemctl stop coin-index-sample.service coin-index-hourly.service
sudo git -C /opt/coin reset --hard <known-good-main-sha>
```

Fix forward on a branch/PR (Claude merges), then pull and re-enable both timers.
To test old code without pulling, source `/etc/coin/index.env` and, from
`/opt/coin`, run `uv run python tools/run_index.py --mode sample` directly; the
key is never typed or printed.

## 7. Env file

`/etc/coin/index.env` (mode 600) is the only place the key lives on the server.
Check it is present without printing it:

```bash
sudo test -f /etc/coin/index.env && echo present
sudo grep -q '^HELIUS_API_KEY=.' /etc/coin/index.env && echo 'HELIUS_API_KEY set'
```

Variables: `HELIUS_API_KEY` (required), `COIN_REPO`, `COIN_INDEX_WORKTREE`,
`COIN_INDEX_ENV`, `COIN_INDEX_LOCK`, `COIN_INDEX_MINTS` (default
`$COIN_REPO/index/seed_mints.txt`) and `COIN_INDEX_DISCOVER_PAGES` (default `10`).
Their defaults are in the first table. No DexScreener key. Never paste the key
into a command, issue, or PR; the script writes neither the key nor the env file
to git or the journal.
