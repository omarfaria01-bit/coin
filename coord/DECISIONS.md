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
