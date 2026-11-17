# Brief — GTA 6 Index coin (any Claude session working on #156)

Read `coord/STATE.md`, then `INDEX_RULES.md` (the rules), then this brief. Tracking issue: #156.

## What and why

kiwi decided (17 Nov 2026) that the first coin on our reward engine is an **index coin for the GTA 6 narrative**:
- it tracks the top 10 GTA 6 memecoins chosen daily by `INDEX_RULES.md`;
- holders earn **SOL** from the existing engine (COIN_MATH v0.3.3, current params);
- draw winners get **prizes paid in the index basket** (INDEX_RULES §7); draws stay off until COIN_MATH §9's enable condition holds.

GTA 6 releases on **19 Nov 2026**. Ship the smallest correct version.

**Out of scope (D24): don't build, don't mention on the site.** Supply vesting, dev-token locks, early-buy vesting, taint/forfeit, underwater boost, treasury bot.

**Launchpad: pump.fun.** Clean launch (hard rule 6): 0% bundle, no team wallet buys except an optional single dev buy in the creation tx from the publicly declared dev wallet. No wash trading, fake volume or hidden wallets.

## Deadlines (Rome time; UTC = Rome − 1h)

- 18 Nov 12:00 — `INDEX_RULES.md` + params merged (#156), G1 report in `reports/`.
- 18 Nov 22:00 — first dry-run top 10 from live data; site preview online.
- 19 Nov — first official index at the 18:00 UTC rebalance. Coin launch only after kiwi's `APPROVED <issue#>`.

## Who does what (Grok is offline)

| Work | Owner | Notes |
|---|---|---|
| Rules, `index/` pure code + tests, reviews, DECISIONS | Claude, cloud session | temporary manager for #156 |
| G1 data research | researcher subagent | done: `reports/research_index_data_2026-11.md` |
| G2 data adapter `adapters/market_data.py` | Claude, cloud session (data-puller / test-writer subagents) | after kiwi decides the F4 source |
| G3 daily job | Claude session on the Hetzner box | cron on the server, 18:00 UTC; commits `index/out/`; no GitHub `workflow` scope needed |
| G4 website | Claude session on the Hetzner box | spec in its own issue |
| G5 red team | Haiku subagents | after G2 |

**Free LLM CLIs on the box (Gemini CLI, OpenCode free models):** only public-docs research and generic code (e.g. reading DexScreener or RPC docs, boilerplate). Never send them `coord/`, this brief, launch timing, wallet addresses or strategy (docs/tooling/CREDIT_SAVING.md, free-tier privacy).

## Site requirements (G4)

Mobile first, static. Sections:
- what the index is;
- live top 10 from the latest `index/out/*.json` (ticker, weight, MC, liquidity, fees, traders, rank change);
- collapsible list of excluded coins with the reason;
- how holders earn, in plain English: SOL rewards and basket prizes, with the date rewards go live once kiwi sets it;
- transparency: declared dev wallet, team and fee wallets, CA placeholder, links to the index JSON;
- FAQ.

Constraints: free static host that works with a private repo (Cloudflare Pages, Vercel or Netlify; kiwi creates the account). No APR, no "earn X%", no promises. No Rockstar logos or official art; "GTA 6" in text only to describe the narrative.

## Rules that still apply

Every hard rule in CLAUDE.md. Computing the index is read-only. Claiming creator fees, buying basket prizes, creating the token, any dev buy and any post need kiwi's `APPROVED <issue#>` from his own login.

**Important:** the cloud Claude session posts through kiwi's GitHub account. Its comments are signed "— Claude (cloud)". They are **never** an approval and never kiwi's directive: only kiwi writes `APPROVED <issue#>`.

## kiwi must provide

Name and ticker · public dev wallet address · X link · OK on keywords and overrides · F4 data source decision · static host account.
