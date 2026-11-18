# GTASP10 public front end (draft, #164)

Static site, vanilla HTML/CSS/JS, no build step, no wallet connect, no contract address yet.

- `index.html`, `style.css`, `app.js` — Italian first, EN toggle (stored in localStorage).
- Reads `data/latest.json` (latest hourly index output) and `data/candidates.json` (latest sample per tracked mint), refreshed every 60 s.
- Empty top 10 → "Top 10 in costruzione" + candidates preview (clearly labelled as NOT members). With members → donut + table with weights, MC, liquidity, volume, rank change.

## Live

https://desk.linkgox.com/gtasp10/ (Hetzner, Caddy `handle_path /gtasp10/*` → `/var/www/gtasp10`, no auth; the rest of desk.linkgox.com keeps basic_auth).

## Data export (server)

`deploy/gtasp10-export.py` → `/usr/local/bin/gtasp10-export.py`, run by `gtasp10-export.timer` every 5 min as root with
`ProtectSystem=strict` and write access only to `/var/www/gtasp10/data`. Read-only on coin data
(`/var/lib/coin/index-data/index/out/*.json`, `/opt/coin/data/index/samples/*.jsonl`). Units: `deploy/systemd-units.txt`.

## Deploy

`scp web/index.html web/style.css web/app.js root@77.42.76.147:/var/www/gtasp10/`
