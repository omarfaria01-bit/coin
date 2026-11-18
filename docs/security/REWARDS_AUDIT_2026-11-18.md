# GTASP10 rewards security audit — 18 Nov 2026

Requested by kiwi ("avvia un qualche tool che trova falle nel sistema rewards", #156). Read-only audit by Grok
(executor). Scope: `engine/` (hourly_draw, draws, sybil_v033, ledger, epoch, rewards), `adapters/helius_parse.py`,
front-end `web/` (PR #266/#270), live site https://desk.linkgox.com/gtasp10/, `/usr/local/bin/gtasp10-{logo,export}.py`
and Caddy config on Hetzner. Base: `origin/main` f2a727e. No transactions, no wallet connections, no load tests,
nothing changed in production.

**Status context:** rewards are not live. `CA = null`, `draws.enabled = false`, the hourly job does not call
`plan_hourly_draw`, the VRF is not wired, and no payout sender exists. Every finding below is a pre-launch fix.

## Tools run

| Tool | Target | Result |
|---|---|---|
| semgrep (p/python, p/security-audit, p/javascript, p/secrets) | repo + web + server scripts | 3 warnings: dynamic `urlopen` (gtasp10-logo.py:82, adapters/solana_read.py:41, tools/check_hubs.py:38) |
| bandit | engine/adapters/tools/index/ops/sim + server scripts | 0 high; 2 medium B310 (same urlopen); lows are false positives |
| gitleaks (469 commits) + trufflehog 3.99.9 (git + files) | repo history, web, server scripts | no secrets found |
| pip-audit | 22 locked deps from uv.lock | no known vulnerabilities |
| npm audit / cargo audit / clippy / sec3-style checks | n/a | no package.json, no Rust/Anchor program (`onchain/` is empty) |
| custom simulation with `engine.hourly_draw` | sybil splitting | see C1 |
| curl (≈15 requests) | live site headers, paths, CORS | see L1 |

## Findings

### Critical

**C1. Splitting into many wallets multiplies draw odds (sqrt odds + no linking for CEX-funded wallets).**
`engine/hourly_draw.py:76-78`, `engine/draws.py:43` (`w = isqrt(score)`), `engine/sybil_v033.py` (hub edges ignored).
sqrt odds reward splitting: N wallets of x/N weigh √N times one wallet of x. The 5% cap is per *cluster*, so splitting
also bypasses it. Wallets funded straight from an exchange (a hub) get no S2/L-edges, so they are never linked.
Measured with the real engine (30 honest holders, attacker holds as much as all of them together):
1 wallet → 5.0% odds, 10 wallets → 36.6%, 100 → 64.6%, 1,000 → 85.2%. Cost per extra wallet ≈ ATA rent + CEX
withdrawal fee + the 1e-6 supply minimum.
Fix: use **linear** odds (score share, split-neutral) or a large per-entrant minimum (e.g. ≥ 0.01% of supply, so
1,000 sybils need 10% of supply); keep the cap; publish cluster stats. sqrt only works with strong identity, which
on-chain heuristics cannot give.

### High

**H1. With fewer than 20 clusters every holder gets equal odds (dust = whale).** `engine/hourly_draw.py:35-36`.
At launch 20 dust wallets would take most of the odds. COIN_MATH §16 says draws need ≥ 100 eligible clusters, but
`plan_hourly_draw` does not enforce it and `is_draw_eligible` (min share) is never called on the hourly path.
Fix: add `min_clusters` (default 100) and the min-share check inside `plan_hourly_draw`, returning `too_few_clusters`.

**H2. "5% cap" is 5% of the odds, not 5% of supply.** `engine/params.py:163`, `hourly_draw.py:18`. The rule described
to kiwi/users ("any holder capped at 5% supply") is not what the code does. Fix: align wording on the site/X, or
add a supply cap on counted balance.

**H3. Operator-controlled inputs can bias a draw before the VRF.** S3 manual merges (`cluster_overrides.json`,
`sybil_v033.py:s3_overrides`), the hub list (`data/hubs`, hubs are removed from holders and their links ignored),
`excluded`, and the event cut-off all change `snapshot_hash`. Anyone running the job can try variants or silently
drop/merge a holder ("frame" by merge). Fix: put `sha256(overrides ‖ hubs ‖ excluded ‖ params ‖ last slot)` inside
the snapshot hash, publish all files, commit the snapshot hash on-chain, then request ORAO VRF with seed = snapshot
hash, exactly one request per draw_index, and no re-request (on timeout → roll over).

### Medium

**M1. Randomness not implemented yet.** `rho` is an input; ORAO is chosen (D8) but there is no request/verify code.
Fix: verifier script that re-derives winners from on-chain snapshot hash + ORAO fulfilled account; fail closed.

**M2. Framing via S2.** `sybil_v033.py:s2_funded_buys`: sending a fresh wallet ≥ 50% of its SOL before its first buy
creates a *strong* edge and merges it into the sender's cluster (sqrt of the sum < sum of sqrt, and the victim's
prize is split with the attacker's members). Fix: S2 only when the funder also signs/received tokens back, or put
S2-only merges in review instead of auto-merging.

**M3. Smart-contract escrows can be counted as holders.** `adapters/helius_parse.py:27-37` excludes only pump.fun,
pump AMM, Raydium v4/CPMM/CLMM, Meteora DLMM, Orca. Meteora DAMM v1/v2, Raydium LaunchLab, lockers (Streamflow,
Jupiter Lock), lending vaults and limit-order escrows are not excluded; a prize sent there is stuck or goes to a
third party. Engine `excluded` comes from a hand-made list. Fix: exclude any owner that is off-curve (a PDA) plus
the dev/treasury wallets, and list them publicly.

**M4. No double-pay guard for pushes.** `engine/epoch.py` push rail + state file: if the job pays on-chain and
crashes before saving state, a rerun pays again. Fix: idempotency key `(epoch|draw_index, wallet)` in the tx memo,
check on-chain before sending, write state before and after.

**M5. Hourly logo trusts DexScreener `imageUrl` and runs as root.** `/usr/local/bin/gtasp10-logo.py:80-83,193-203`;
unit `gtasp10-logo.service` has no `User=`. Any top-10 coin creator controls the image placed in the official logo
(content poisoning: offensive image or a "send SOL here" QR on the X avatar); `urlopen` accepts any scheme/host with
unbounded size (SSRF to 127.0.0.1:2019 is GET-only and blind, low impact). Fix: https only, host allowlist,
5 MB cap, `Image.MAX_IMAGE_PIXELS`, run as an unprivileged user, and a human check before the image goes to X.

### Low

**L1. Live site has no Content-Security-Policy.** Headers are otherwise good (HSTS, nosniff, X-Frame-Options DENY,
Referrer-Policy no-referrer, no `Server`, no CORS header, `.git`/`.env`/deploy files 404, path traversal 404).
Fix (Caddy `handle_path /gtasp10/*`): `default-src 'self'; img-src 'self' https://dd.dexscreener.com
https://*.dexscreener.com data:; connect-src 'self' https://api.dexscreener.com; frame-src https://dexscreener.com;
script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'`.
**L2. Holding-time curve saturates at 4h** (D27): a 5h flipper earns 0.53× a long holder; flash-buy before the
snapshot is blocked by T_START = 1h. By design; noted.
**L3. Prize rounding** floors and conserves (`Σ prizes + rollover = pot`, tested). Rollover minimum 0.01 SOL is fine.
**L4. Board preview ranks by DexScreener market cap** (`web/app.js` preview) — fake caps can show until the official
index replaces it; marked "preview" on the page.

## Checked and OK
- Rewards lookup is a static JSON fetch `data/wallets/<encodeURIComponent(addr)>.json` after a base58 regex check;
  all dynamic text goes through `esc()`; no wallet connection, no signatures.
- A pasted seed phrase is detected client-side and never sent anywhere; the page says it will never ask for a seed
  phrase or private key. No such request exists in the repo or on the server.
- Draw sampler: rejection sampling has no modulo bias; domain-separated, fixed-width hash input.
- Ledger: transfers between unlinked wallets reset age; flash buys score 0 for 1h.
