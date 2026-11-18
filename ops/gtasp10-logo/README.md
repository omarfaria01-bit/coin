# GTASP10 live logo

Hourly renderer for the GTASP10 "heist bag" logo: the 10 coin-stack faces show the
logos of the current GTASP10 top 10 (index weight order); the 11th face is a gold `10` emblem.

- Source order: index members (latest `/var/lib/coin/index-data/index/out/*.json`, by weight)
  -> fallback: sane `candidates.json` entries + static GTA list ranked by live DexScreener
  market cap (liquidity >= $10k) -> static list.
- Logos from DexScreener `info.imageUrl` (CDN params `width=800&height=800&quality=95&format=auto`),
  cached in `/var/cache/gtasp10-logo` (24h). Missing logo -> ticker text. GTA VI (`4kjru…`) has a
  placeholder image upstream, so it is drawn as `GTA VI` text.
- Output (atomic): `/var/www/gtasp10/logo.png` (1024), `logo-400.png`, `logo.json` (as_of, source, coins).
- Deploy: script -> `/usr/local/bin/gtasp10-logo.py`, template -> `/usr/local/share/gtasp10/logo_template.jpg`,
  units -> `/etc/systemd/system/`, `systemctl enable --now gtasp10-logo.timer` (hourly at :07 UTC).
- Read-only on index data; only public DexScreener GETs. No wallets, no posting.
