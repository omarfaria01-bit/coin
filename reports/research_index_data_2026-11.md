# G1 — Data sources for the GTA 6 index (17 Nov 2026)

Researcher subagent, public docs only, pages read on 17 Nov 2026 (#156). Several official pages (Birdeye, Helius, GMGN) could not be reached from the session, so those rows are **UNVERIFIED** and must be checked on the live docs before code depends on them.

| Filter / input | Best source found | Endpoint / field | Access | Confidence |
|---|---|---|---|---|
| Discovery (new pump.fun tokens) | PumpPortal-style stream | `subscribe_new_tokens` → `mint`, `name`, `symbol`, `uri`, `creator` | keyless, 2 free sockets | medium |
| Discovery (search existing pairs) | DexScreener | `GET /latest/dex/search` | free | medium |
| MC, liquidity (F2, score) | DexScreener | `/tokens/v1/{chain}/{tokens}` → `marketCap`, `liquidity.usd` | free | medium |
| Volume 24h (F10) | DexScreener | `volume.h24` (key not confirmed on the page) | free | low |
| Unique traders 24h (F9, score) | Birdeye | `uniqueWallet24h` | UNVERIFIED | low |
| Top 10 holders (F3) | Solana Tracker | `risk.top10` (unclear whether pool vaults are excluded) | paid (Premium) | low–medium |
| Total fees (F4, score) | **none confirmed** | GMGN's API is described by a third party as closed/subscription; no official doc reached | — | low |
| Bundle at launch (F5) | Solana Tracker | `risk.bundlers.totalPercentage` | paid (Premium) | medium |
| Dev holding (F6) | Solana Tracker | `risk.dev.percentage` | paid (Premium) | low |
| Serial creator (F7) | not found | — | — | low |
| Authorities (F8) | Helius DAS `getAsset` / RPC `getAccountInfo` on the mint | field names UNVERIFIED | RPC | low |
| Curve vs graduated | Solana Tracker | `pools[].market`, `pools[].curvePercentage` | paid (Premium) | medium |
| pump.fun mint type (#18) | not verified | one undated secondary source says SPL | — | low |

## Gaps that block a real index

1. **F4 total fees:** no confirmed official source. Options for kiwi (decision needed):
   - compute it on-chain: sum fee + priority fee + tips of every transaction that traded the token (heavy for old coins, fine for coins a few days old);
   - an official GMGN API if kiwi has legitimate access;
   - drop F4 from the score and keep it only as a filter once a source exists.
2. **F7 serial creator:** compute on-chain from the creator's create transactions (RPC `getSignaturesForAddress` + pump.fun create instruction).
3. **F3 top 10:** compute ourselves from RPC `getTokenLargestAccounts`, removing pool/curve vaults and hubs, instead of trusting a field whose definition is unclear.
4. **F9 unique traders:** verify Birdeye on its live docs; fallback: count signers of swap transactions on-chain.
5. **#18 mint type:** check one fresh pump.fun mint on-chain (owner program = SPL Token or Token-2022).

## Recommended stack for the dry run

DexScreener (free) for discovery, MC, liquidity and volume, plus our own RPC/Helius calls for F3, F7, F8 and #18. Solana Tracker Premium covers F5/F6 and curve status in one call but costs money: kiwi decides. GMGN: no scraping (terms).

Sources: [PumpPortal-style stream](https://pumpdatamonorepository.pages.dev/data-api/subscribe-new-tokens) · [DexScreener API](https://docs.dexscreener.com/api/reference) · [Solana Tracker datastream safety](https://docs.solanatracker.io/guides/datastream-safety.md) · [Solana Tracker risk](https://docs.solanatracker.io/data-api/risk) · [Mobula: GMGN alternatives (third party)](https://docs.mobula.io/guides/gmgn-alternatives) · [DexTools pump.fun guide (secondary)](https://www.dextools.io/news/what-is-pump-fun-solana-memecoin-launchpad-2026)
