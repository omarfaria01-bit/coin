# Claim rail if the launch mint is Token-2022 (issue #18)

Access date for every source below: **2026-11-14** (Europe/Rome, CET).
Method: official docs and GitHub source first; program IDs and rent were checked read-only with `solana program show` / `getMinimumBalanceForRentExemption` against `https://api.mainnet-beta.solana.com` and `https://api.devnet.solana.com` (solana-cli 4.1.2). No wallets were connected. No transactions were sent. No keypairs were used.

This report answers the five questions in #18 and recommends a claim rail for (a) a legacy SPL mint and (b) a Token-2022 mint. Claude records any DECISIONS.md change. It follows up items 2–3 and 8 in `reports/research_onchain_2026-11.md` §6.

**License caveat (same as #10):** calling a deployed GPL program is fine; do not vendor GPL source into this repo.

---

## 1. Maintained jito/jup forks that use `token_interface` / Token-2022?

**Short answer: none of the jito or jup merkle-distributor programs (default branches or listed feature branches) implement `token_interface`. There is no maintained jito/jup merkle rail for a Token-2022 mint.**

### 1.1 jito-foundation/distributor

- Repo: [jito-foundation/distributor](https://github.com/jito-foundation/distributor), license **GPL-3.0**, 73 stars.
- Default branch `master`. Last default-branch commit `2cf79f6397` (“Add priority fees…”) **2024-04-04 18:28 Europe/Rome (CEST)**. `pushed_at` 2025-04-30 20:37 Europe/Rome (CEST).
- Branches on 2026-11-14: `docs`, `evan/anchor-0.30`, `fix-underscore`, `lb/increase_rate_limits`, `license`, `master`, `revert-4-lb/increase_rate_limits`. None are Token-2022 related.
- A checkout of `master` (and a filename/content search) shows `Program<'info, Token>` / `anchor_spl::token::Token` only. No `token_interface`, no `Token-2022`.
- This is the parent of the D7 program, not a Token-2022 option.

### 1.2 jup-ag/distributor (D7 program, and the `mass_send_token_2022` branch)

- Repo: [jup-ag/distributor](https://github.com/jup-ag/distributor), license **GPL-3.0**, 31 stars.
- Default branch `master`, commit `304c28a4e1` (as in D7 / PR #10), `pushed_at` 2026-05-28 19:11 Europe/Rome (CEST).
- `master` still declares `Program<'info, Token>` and program ID `DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R`. Verified deployed on **mainnet and devnet** today (same ID, upgradeable). Mainnet upgrade authority: `CvQZZ23qYDWF2RUpxYJ8y9K4skmuvYEEjH7fK58jtipQ`. Data length 1,023,776 bytes. Audit PDF: still **UNVERIFIED** (Jupiter audits page does not list this distributor).
- Branches include `mass_send_token_2022` (latest commit `38653d2b4e` “refactor”, 2025-09-15 05:02 Europe/Rome (CEST), plus a “WIP” commit). **This branch is not a Token-2022 merkle program.** The on-chain `new_claim` still has `token_program: Program<'info, Token>`. What the branch adds is a **CLI `MassSend`** in `cli/src/bin/instructions/process_send.rs` that inspects `mint.owner` and calls either `spl_token_2022::instruction::transfer_checked` or classic `spl_token::instruction::transfer`, creating ATAs with the mint’s token program. That is a **push** helper, not a `token_interface` claim rail.
- The same branch changes `declare_id!` to `DiSLRwcSFvtwvMWSs7ubBMvYRaYNYupa76ZSuYLe6D7j` (and `security_txt` still says jup.ag). That ID **is deployed on mainnet** (upgrade authority **the same Jupiter key** `CvQZZ23q…`, data length 819,600 bytes, last deployed slot 283095880) and is **not present on devnet** (`solana program show` → account not found). Treat it as a second Jupiter merkle deployment, still **legacy SPL** (see Meteora IDL below). Do not use it for Token-2022 claims.

### 1.3 Meteora GitHub org

Searched [MeteoraAg](https://github.com/MeteoraAg) for distributor / merkle / airdrop (2026-11-14):

| Repo | What it is | Token-2022 merkle? |
| --- | --- | --- |
| [MeteoraAg/merkle-distributor-sdk](https://github.com/MeteoraAg/merkle-distributor-sdk) | TypeScript **client** (`@meteora-ag/merkle-distributor-sdk` v1.0.1, **MIT**, 0 stars). Last commit `e09363ffdf` 2026-11-04 10:04 Europe/Rome (CET). README program ID: `DiSLRwcSFvtwvMWSs7ubBMvYRaYNYupa76ZSuYLe6D7j` (mainnet = “devnet”, but see RPC result above: **devnet account missing**). | **No.** The shipped IDL pins `token_program` to `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA` on `new_claim` / `new_distributor`. `merkleDistributor.ts` hard-codes `TOKEN_PROGRAM_ID`. Proofs are fetched from a `claimProofEndpoint` the caller must host. |
| [MeteoraAg/liquidity-distributor-sdk](https://github.com/MeteoraAg/liquidity-distributor-sdk) | SDK for program `pDisRpxvnFw4osSqDPqMJ62tLsVQGsHL4tMX23ArYrL` (verified mainnet **and** devnet today; different binary size on the two clusters). README: distributes **liquidity NFTs**, not our epoch token claims. Last commit `5d3bc65fc6` 2026-11-04 10:04 Europe/Rome. License: **UNVERIFIED** in package metadata (GitHub license API was empty). | Not a token-claim merkle rail. |
| [MeteoraAg/cloudflare-kv-merkle-proof](https://github.com/MeteoraAg/cloudflare-kv-merkle-proof) | Example proof host. | N/A |

No Meteora on-chain merkle-distributor **source** repo was found (SDK + IDL only). No `token_interface` merkle program in this org.

### 1.4 Other public Token-2022 merkle program found (not a jito/jup fork we should default to)

[okxlabs/Boost-TokenDistributor-Solana](https://github.com/okxlabs/Boost-TokenDistributor-Solana) — MIT, 2 stars, program ID `2Ab8No85xrnnd2rFamKjQqGAK6Qu9EQ4eEh59oaZEPBL`.

- README and tests explicitly support SPL **and** Token-2022 **except** mints with the TransferFee extension.
- Leaf (from `tests/utils/merkle_tree.ts`, accessed today): `sha256(claimant[32] || amount_u64_le)` with **no** 0x00/0x01 prefixes; intermediate nodes are `sha256(min(left,right) || max(left,right))`; odd levels **duplicate** the last node. This is **not** the D7 / jup leaf (which also includes `amount_locked` and the prefixes).
- Verified on **mainnet and devnet** today. Mainnet upgrade authority is **`none`** (immutable). Devnet still has upgrade authority `3gmBN8LBomg3sZEjTgp2YsECMYgJpjcT7xUfpnDB4gSs`.
- Audit: [Boost Solana Audit Report.pdf](https://github.com/okxlabs/Boost-TokenDistributor-Solana/blob/main/audit/Boost%20Solana%20Audit%20Report.pdf), **OKX Web3 Audit Team, 2025-08-07**, base/final commit `0b00464112`. Findings: 0 critical/high/medium; 1 Low “Centralization Risk” (`set_merkle_root` can be updated by the operator — **confirmed, not fixed**); 1 Info. This is a **first-party** audit, not an independent firm.
- After the audit, GitHub issue [#3](https://github.com/okxlabs/Boost-TokenDistributor-Solana/issues/3) (opened 2026-04-03, still **open** as of today) describes missing validation for Token-2022 **TransferFee** mints (underfunded vault). README now says TransferFee mints are unsupported, but the issue argues `create_distributor` still does not reject them.
- Last default-branch commit `9ea1ae6c87` 2026-05-08 11:22 Europe/Rome (CEST) is a README/audit-link update, not a program change.
- **Do not pick this as the v1 Token-2022 rail:** tiny community (2 stars), operator-updatable merkle root, first-party audit, open TransferFee issue, leaf incompatible with our D7 Python tree. Immutable mainnet program is a plus, but not enough.

---

## 2. Streamflow Airdrop

Official IDs: [developers.streamflow.finance/docs/resources/program-ids](https://developers.streamflow.finance/docs/resources/program-ids). Airdrop program `MErKy6nZVoVAkryxAejJz2juifQ4ArgLgHmaJCQkU7N` — **same ID on mainnet and devnet**, both verified today. Mainnet last deployed slot 449057115, data length 749,344 bytes, upgrade authority `5u7o2WGgHckh18opTfPsqKb8E3nhDKcReBrbzUeXg2n7`. Devnet last deployed slot 498127760, data length **746,568 bytes** (binary is **not identical** to mainnet), upgrade authority `HCP4jd677aMUGhEXRYWkdKXHGd3LcyidHJWWxdb9TxLM`.

### 2.1 Does it accept Token-2022 mints? **Yes (sourced)**

- Neodyme, [Security Audit – Streamflow Distributor](https://neodyme.io/reports/Streamflow-Distributor.pdf), **11 June 2024** (audit April 2024, small change reviewed 10 June 2024): “The Streamflow distributor is a fork of https://github.com/jito-foundation/distributor and extends it by adding an instruction for an admin to close claims, a mechanism for continuous unlocks as well as **support for SPL Token-2022**.” 0 critical / high / medium. (This is a newer, distributor-specific PDF than the `Streamflow-Protocol.pdf` cited in #10; both exist on neodyme.io today.)
- Public SDK [streamflow-finance/js-sdk](https://github.com/streamflow-finance/js-sdk) (`packages/distributor`, last commit `fb236fff32` 2026-09-01 01:36 Europe/Rome (CEST), 166 stars, **GPL-3.0**): `BaseDistributorClient` calls `getMintAndProgram` and passes the resulting `tokenProgramId` into ATAs and instruction accounts. `getMintAndProgram` in `packages/common/solana/utils.ts` accepts both `TOKEN_PROGRAM_ID` and `TOKEN_2022_PROGRAM_ID`. Official docs: [getMintAndProgram()](https://developers.streamflow.finance/docs/api/common/functions/getMintAndProgram) (“supports all Token Programs”). The distributor API surface also exports `calculateAmountWithTransferFees` ([docs](https://developers.streamflow.finance/docs/api/distributor/solana)).
- On-chain program **source is still not public** (`streamflow-finance/protocol` is 404, same as #10). Token-2022 support is attested by the audit + the official SDK, not by a readable `token_interface` crate in an open program repo.

### 2.2 Is the leaf / hash format published? **No — still UNVERIFIED**

The public SDK does not contain a leaf hasher (confirmed today by searching `packages/distributor` for hash/leaf constructors). Trees are produced by Streamflow’s HTTP API `https://api-public.streamflow.finance/v2/api/airdrops/` (multipart CSV: `pubkey,amount_unlocked,amount_locked,category`), documented in the official [SDK module docs](https://js-sdk-docs.streamflow.finance/modules/_streamflow_distributor.html). The Neodyme report describes verification as “claim data and the co-path … to the pre-saved Merkle root” but does **not** specify hash function, field order, endianness, or 0x00/0x01 prefixes.

Because Streamflow is a jito fork, the leaf *might* match D7 — **do not assume that**. `engine/merkle.py` cannot target this program until Streamflow publishes the exact leaf and parent hash, or an official open program repo.

### 2.3 Tree API without a manually issued key? **No**

The same official SDK docs state: the public API “is accessed with an auth token passed in in the `x-api-key` header … The tokens are provided **manually by Streamflow** by reaching out to us with the wallet address that will create the Airdrop.” There is no documented key-free official hasher. Rolling our own tree would be guessing the leaf.

Claim fee: SDK constant `AIRDROP_CLAIM_FEE = 10_000_000` lamports (0.01 SOL) is still in the package (as reported in #10). Live oracle vs constant: **still UNVERIFIED**.

---

## 3. Which launchpads mint Token-2022 vs legacy SPL?

The acquaintance’s pad is still unknown (`config/pad.json` unfilled). The engine stays pad-agnostic. Current public pads (official sources, today):

| Pad | Default / created mint | Source (accessed 2026-11-14) |
| --- | --- | --- |
| **pump.fun `create_v2`** | **Token-2022 always.** Account 8 is `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`. Mint is initialized as Token-2022, 6 decimals, metadata pointer on the mint. | [pump-fun/pump-public-docs `COIN_CREATION.md`](https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/COIN_CREATION.md). Official Telegram note (11 Nov, year not restated in the scrape; the current docs still describe `create_v2` this way): new coins use Token-2022; older coins created with legacy `create` stay on classic SPL Token. |
| **pump.fun legacy `create`** | **Legacy SPL Token** (pre-`create_v2` coins). | Same official update thread / docs split. |
| **Raydium LaunchLab** | **Either.** The program can create a Token-2022 base mint via `initialize_with_token_2022` (always `MetadataPointer`, optional `TransferFeeConfig` ≤ 5%). Pre-existing arbitrary Token-2022 bases cannot be used. Classic SPL bases are also supported (LaunchLab “Yes” for both in the product table). | [docs.raydium.io Token-2022 support matrix](https://docs.raydium.io/reference/token-2022-support), [SPL Token and Token-2022](https://docs.raydium.io/solana-fundamentals/spl-token-and-token-2022). |
| **Meteora DBC** | **Either, chosen in the config.** “DBC can launch an SPL Token or Token 2022 base mint.” Token-2022 bases get metadata (+ optional `TransferFeeConfig` or a transfer hook that is **revoked at graduation**). New Token-2022 configs migrate to DAMM v2. | [docs.meteora.ag DBC Token 2022 Support](https://docs.meteora.ag/core-products/dbc/token-2022-support), [DBC Launch Configuration](https://docs.meteora.ag/core-products/dbc/launch-configurations). |

**Implication:** a pump-style launch is Token-2022, so **D7 (jup merkle) cannot pay that mint**. A LaunchLab or DBC launch might be either; read `pad.json` / the actual mint owner at pad-watch time.

---

## 4. Push-payout cost for Token-2022 (new recipient ATA)

Read-only `getMinimumBalanceForRentExemption` on mainnet today (slot 469139804):

| Account data length (bytes) | Rent-exempt minimum (lamports) | SOL |
| --- | ---: | ---: |
| 165 (classic SPL token account / Token-2022 base `Account::LEN`) | 1,488,440 | 0.00148844 |
| 170 | 1,513,840 | 0.00151384 |
| 178 | 1,554,480 | 0.00155448 |
| 182 | 1,574,800 | 0.00157480 |

**Which size applies?** Official Associated Token program for Token-2022 always requests space for `ExtensionType::ImmutableOwner` plus whatever the mint requires (`get_account_len` in [associated-token-account `processor.rs`](https://github.com/solana-program/associated-token-account/blob/main/program/src/processor.rs) and [`tools/account.rs`](https://github.com/solana-program/associated-token-account/blob/main/program/src/tools/account.rs), which CPI `get_account_data_size` on the Token-2022 program). `Account::LEN` is 165 in [solana-program/token-2022 `interface/src/state.rs`](https://github.com/solana-program/token-2022/blob/main/interface/src/state.rs). A typical Token-2022 ATA with only ImmutableOwner is **170 bytes** (165 + 1 account-type + 4-byte TLV header + 0 data) → **1,513,840 lamports**. If the mint also requires `TransferFeeAmount` on every token account, the size is larger; **re-query `GetAccountDataSize` for the live mint** at integration (do not hard-code).

**Transaction fee:** Solana’s default **base fee is 5,000 lamports per signature**. Priority fees are extra and market-dependent (UNVERIFIED as a fixed number). A one-signature transfer therefore has a 5,000 lamport floor.

**Cost if every recipient needs a new ATA** (rent paid by us in a push; no priority fee; 1 signature per recipient, no batching):

| Recipients | Rent at 170 B (typical T22 ATA) | Base tx fees (N × 5,000) | Total (no priority) |
| ---: | ---: | ---: | ---: |
| 100 | 0.151384 SOL | 0.000500 SOL | **≈ 0.1519 SOL** |
| 500 | 0.756920 SOL | 0.002500 SOL | **≈ 0.7594 SOL** |

If the mint forces a larger account (example: 182 B), 100 recipients ≈ 0.1575 + 0.0005 = **0.1580 SOL**; 500 ≈ **0.7900 SOL**.

If ATAs already exist, rent is **zero** and only tx fees (and any Token-2022 transfer fee on the mint) remain. Batching several transfers per transaction (the jup `MassSend` CLI does this, `max_address_per_tx`) cuts **tx count**, not rent. Under the §13 rule (push when eligible < 500), worst-case rent is on the order of **0.76–0.79 SOL per epoch** plus priority fees — small relative to a typical pot, but it must be funded.

Claim-based rails usually make the **claimer** pay ATA rent (jup / Streamflow model). Push shifts that cost to us.

---

## 5. Recommendation (Claude decides)

### (a) Legacy SPL Token mint

**Keep D7:** call [jup-ag/distributor](https://github.com/jup-ag/distributor) at `DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R`, leaves as implemented in `engine/merkle.py` (PR #30). Push payouts remain the fallback when eligible < 500 (COIN_MATH §13).

### (b) Token-2022 mint

**There is no maintained, open-source, `token_interface` jito/jup merkle program we can point `engine/merkle.py` at today.**

1. **Default v1 rail for a Token-2022 mint: push payouts** (the §13 path, not limited to “small N” if merkle is unavailable). Use Token-2022 `transfer_checked` + idempotent ATA create, sized from `GetAccountDataSize` on the live mint. The jup `mass_send_token_2022` CLI is a useful **reference** for the transfer fork; do **not** vendor that GPL CLI. Budget rent as in §4. This needs no new on-chain program and no API key.
2. **Merkle alternative, only if we must have claims for large N:** Streamflow Airdrop (`MErKy6nZVoVAkryxAejJz2juifQ4ArgLgHmaJCQkU7N`). It is the only **maintained, independently audited** (Neodyme, June 2024) distributor with documented Token-2022 support. Blockers to use it with our engine: (i) leaf format unpublished, so we cannot generate our own proofs; (ii) official tree API requires a **manually issued API key**. If kiwi obtains a key *and* Streamflow publishes the leaf (or we accept their API as the sole tree builder), Claude can record a follow-up decision. Do not guess a jito-compatible leaf.
3. **Do not** use Meteora’s `DiSLRwcS…` merkle program or the jup `mass_send_token_2022` **on-chain** program for Token-2022 claims (IDL / source still pin legacy `Tokenkeg`).
4. **Do not** default to OKX Boost (`2Ab8No85…`): first-party audit, operator-updatable root, open TransferFee issue, incompatible leaf, tiny community.
5. **Do not** deploy a custom Foundation-example fork unless Streamflow stays blocked and push is operationally unacceptable. Writing/deploying a program is out of scope for this issue.

Suggested DECISIONS footnote for Claude: D7 remains valid **only for a legacy SPL mint**. If the launch mint’s owner is `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`, v1 pays by **push** until a sourced merkle leaf exists (Streamflow publication or an audited `token_interface` fork).

---

## 6. Candidate program table

Columns match `reports/research_onchain_2026-11.md` §1.1. Access date 2026-11-14 Europe/Rome.

| Program | Repo | License | Stars | Last default-branch commit | Mainnet program ID | Devnet program ID | Audit | Leaf fully specified here? | Token-2022 in source? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Jupiter Merkle Distributor (D7) | [jup-ag/distributor](https://github.com/jup-ag/distributor) `master` | GPL-3.0 | 31 | 2025-02-13 (`304c28a4e1`); `pushed_at` 2026-05-28 | `DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R` (verified) | **Same ID**, verified | **UNVERIFIED** (no PDF on Jupiter audits page) | Yes (D7 / `engine/merkle.py`) | **No** — `Program<Token>` only |
| Jupiter second deployment / Meteora merkle SDK target | jup branch `mass_send_token_2022` (`38653d2b4e`, 2025-09-15); client [MeteoraAg/merkle-distributor-sdk](https://github.com/MeteoraAg/merkle-distributor-sdk) (MIT, 0 stars, `e09363ffdf` 2026-11-04) | Program source GPL-3.0 (jup branch); SDK MIT | 31 / 0 | See left | `DiSLRwcSFvtwvMWSs7ubBMvYRaYNYupa76ZSuYLe6D7j` (verified; same upgrade authority as D7) | **Not deployed** (account missing) | **UNVERIFIED** | Not re-derived here (jup-like) | **No** — IDL and `new_claim` pin `Tokenkeg`. Branch name refers to a **push CLI** |
| Streamflow Airdrop | No public program repo. Client: [streamflow-finance/js-sdk](https://github.com/streamflow-finance/js-sdk) `packages/distributor` | GPL-3.0 (SDK) | 166 (SDK) | SDK `fb236fff32` 2026-09-01 01:36 Europe/Rome (CEST) | `MErKy6nZVoVAkryxAejJz2juifQ4ArgLgHmaJCQkU7N` (verified) | **Same ID**, verified (binary size ≠ mainnet) | [Neodyme, 11 Jun 2024](https://neodyme.io/reports/Streamflow-Distributor.pdf) — 0 crit/high/medium; explicitly adds Token-2022 | **No — UNVERIFIED.** Official API builds the tree; hasher not in the SDK | **Yes** (audit + official SDK `getMintAndProgram` / `tokenProgramId`) |
| OKX Boost TokenDistributor | [okxlabs/Boost-TokenDistributor-Solana](https://github.com/okxlabs/Boost-TokenDistributor-Solana) | MIT | 2 | README `9ea1ae6c87` 2026-05-08; program commit in audit `0b00464112` | `2Ab8No85xrnnd2rFamKjQqGAK6Qu9EQ4eEh59oaZEPBL` (verified; upgrade authority **none**) | **Same ID**, verified (upgrade authority still set) | [OKX Web3 Audit Team, 2025-08-07](https://github.com/okxlabs/Boost-TokenDistributor-Solana/blob/main/audit/Boost%20Solana%20Audit%20Report.pdf) (first-party). Later open issue #3 on TransferFee | Yes, but **different from D7** (`sha256(claimant \|\| amount_u64_le)`, no prefixes, no locked amount) | **Partial** — Token-2022 except TransferFee; issue #3 still open |
| Solana Foundation Merkle Tree Token Claimer | [solana-foundation/program-examples](https://github.com/solana-foundation/program-examples) `tokens/merkle-tree-token-claimer` | MIT | 1436 (monorepo) | Repo active (see #10; not re-checked commit-by-commit today) | Not a shared official deployment | Same | Example only | Yes (see #10 §1.4) | Not a hosted Token-2022 rail; would need a custom deploy |

---

## 7. Still UNVERIFIED / follow-ups

- Exact live Streamflow claim fee (oracle vs 0.01 SOL SDK constant).
- Streamflow leaf bytes (hash, prefixes, field order).
- Whether a later, unpublished Streamflow program build changed the leaf since the June 2024 audit (mainnet vs devnet binaries already differ in size).
- Jupiter audits page still has no distributor PDF.
- Exact Token-2022 ATA size **for our mint** once `pad.json` / extensions are known (`GetAccountDataSize`).
- pump.fun transfer-hook policy (item 8 in the #10 report) — still UNVERIFIED; not required to choose a claim rail.
