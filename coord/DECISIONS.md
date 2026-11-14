# DECISIONS (ADR log)

Format: ID · date · decision · why · alternatives.

## D1 · 2026-11-14 · Repo is private; branch protection pending kiwi
Why: the Action runs with secrets on @claude; public issues invite injected instructions.
Free private personal repos have no enforced branch protection, so "only Claude merges" is a
rule until kiwi picks a paid plan or an org + fork workflow (needs:kiwi issue).

## D2 · 2026-11-14 · float64 for scores, int for money; floor payouts, ceil locks
Why: determinism with Python floats is fine when operation order is fixed; all paid/stored
amounts are ints so conservation is exact. Alternatives: Fraction/Decimal everywhere (slow, no
benefit for byte-identical claims once payouts are ints).

## D3 · 2026-11-14 · Cluster id = smallest wallet id in the cluster
Why: deterministic and stable when unrelated wallets join/leave. Alternative: hash of members
(changes whenever membership changes).

## D4 · 2026-11-14 · Provisional params where COIN_MATH is silent
`min_epoch_payout` 0.01 SOL, push `min_transfer` 0.001 SOL, draw `min_balance_usd` $10,
`lst_fraction` 0 (no LST until decided), `mc_early_usd` none (time window only). Marked
PROVISIONAL in engine/params.py; tune with the simulator.

## D5 · 2026-11-14 · Tool/download policy (kiwi's directive)
Claude and Grok may install/download anything from official sources without a review issue,
logged in #1 / here. Still forbidden: wallets, browser extensions, pirated software, anything
asking for keys. Key/money/publishing rules unchanged.

## D6 · 2026-11-14 · Claude Code runs only in kiwi's sessions and the GitHub Action
Not on Grok's computer; kiwi's Claude login never goes on a machine another agent controls.
Comments from `claude[bot]` / `github-actions[bot]` produced by `.github/workflows/claude.yml`
in this repo are Claude.

## D7 · 2026-11-14 · Merkle claims: jup-ag/distributor (`DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R`)
Leaf per reports/research_onchain_2026-11.md §1.2 (sha256, 0x00/0x01 prefixes, claimant‖u64le‖u64le).
New `version` + vault per epoch. We call the deployed program and write our own Python leaf
code; no GPL source is vendored. **Valid only for a legacy SPL mint**: the program uses
`Program<Token>`. Token-2022 rail is open (#18). Alternatives: Streamflow airdrop (leaf
unpublished), Saber (stale), self-deployed Foundation example (last resort).

## D8 · 2026-11-14 · VRF: ORAO Classic (`VRFzZoJdhFWL8rkvu87LpKM3RbcVezpMEc6X5GVDr7y`)
Seed = published snapshot hash; output consumed off-chain by `engine/draws.py`. Same ID on
devnet/mainnet, Apache-2.0, 0.001 SOL/request (re-read NetworkState at integration).
Alternative: Switchboard On-Demand (price unverified).

## D9 · 2026-11-14 · Dev-token lock: Streamflow Token Lock, `transferableByRecipient=false`
Cancellation impossible by construction. Fallback: Jupiter Lock with cancel + recipient-change
both `None` (upgradeable program, source repo 404 on 2026-11-14 — note publicly if used).

## D10 · 2026-11-14 · `vesting_mode` default `soft`
Raydium CPMM/CLMM reject hooks, Meteora DBC strips them at graduation, Jupiter Trigger excludes
them. Switch to `native` only with a sourced pad finding.

## D11 · 2026-11-14 · Grok implements the remaining engine modules; Claude specs and reviews
kiwi's directive (work never stops, reuse-first). ledger/twab/scoring/rewards/fees/vesting/
merkle/epoch move to `owner:grok` issues with exact specs (#13–#17, #26). Claude reviews money
code line by line. Legal opinion (#8) is handled by kiwi with his lawyers and does not block
engineering; it still gates PUBLIC_RULES.md and P7 (COIN_MATH §16).

## D12 · 2026-11-14 · Free CLIs allowed for simple, non-secret work
kiwi authorized `gemini -p` and `opencode run -m opencode/deepseek-v4.1-flash-free` (plus
Haiku subagents in `.claude/agents/`) for research/drafts/boilerplate. Never send them keys,
`.env`, `coord/` strategy or unreleased launch details; every fact they return is re-checked
at the primary source. Routing Claude Code itself through a gateway stays off.

## D13 · 2026-11-14 · Price unit inside the engine = lamports per token base unit
`Lot.cost_lamports_per_token`, all `twap` arguments to ledger/scoring/vesting use it.
`PricePoint.price` (SOL per whole token) is converted once in the orchestrator:
`lamports_per_base = price · 1e9 / 10**decimals`. Why: BUY cost is `lamports/amount` with no
conversion, so comparisons are unit-safe.
