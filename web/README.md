# GTASP10 public site

Static HTML, CSS and JS. No build step. English only. Relative links, so the same files work at `https://gtasp10.xyz/` and `https://desk.linkgox.com/gtasp10/`.

Pages: `index.html` (home), `index-table.html` (live top 10), `rewards.html`, `backtest.html`, `docs.html`, `faq.html`, `disclaimer.html`.

`rules.js` is generated from `index/params.json` and the reward code:

```
uv run python tools/gen_web_rules.py
```

The index page reads `data/latest.json` and `data/candidates.json` (exported on the server, not committed). The backtest page reads `data/backtest.json`, written by:

```
uv run python sim/backtest.py --index-dir /path/to/index/out --out web/data/backtest.json
```

Script sources are local. The content-security policy allows no external scripts.
