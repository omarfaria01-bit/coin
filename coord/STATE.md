# STATE

last_tick: 2026-11-14 (Action manager; merged #46 #48 #47 #49; D15 = 36h)
updated: 2026-11-14
phase: P1 decisions done → P2 engine build (Grok) + P3 sim harness

## Done
- P0 setup, CI (gitleaks fixed via #22), Haiku subagents (#9), on-chain research (#10).
- Decisions D7 Merkle=jup distributor (SPL only), D8 ORAO VRF, D9 Streamflow lock,
  D10 vesting soft, D11 Grok builds engine, D12 free CLIs, D13 price unit.
- ENGINE_DESIGN v0.3: §8 epoch orchestrator spec.

## Open PRs
- none. Merged: #11 #23 #24 #27 #28 #30 #31 #33 #34 #35 #36 #37 #40 #41 #42.
- D15: unlock_twap_hours default 36h (sweep #43: 24h fails 1h 3.1×/3.5× pump). Merged also #26 #43 #44 #45.

## Grok queue (status:todo)
#51 run_epoch CLI (offline) · #52 golden epoch replay · #53 tx→TokenEvent parser (fixtures) · #54 e2e param sensitivity · #55 runbook + dry-run checklist

## Open / blockers
- Claude Action errors on every @claude (#6, needs kiwi: app + token).
- Kiwi's GH token lacks `workflow` scope → workflow edits go through Grok.
- Main not protected (#7). Legal (#8) is kiwi's, not blocking engineering (D11).
- D6 conflict: this session runs Claude Code on the bot box with kiwi's GH token (kiwi's call).
- Top technical risk: Token-2022 mint ⇒ D7 rail doesn't work (#18).

## Next 3 actions (Claude)
1. Review Grok PRs for #51-#55 (money code line by line).
2. #29 pad_rewards: needs kiwi OK + legal (#8) before enabling.
3. Mint program choice (SPL vs Token-2022) with kiwi before any onchain work.
