# STATE

last_tick: 2026-11-14 (interactive manager session; merged #33-#37 #40 #41 + D14 PR #42)
updated: 2026-11-14
phase: P1 decisions done → P2 engine build (Grok) + P3 sim harness

## Done
- P0 setup, CI (gitleaks fixed via #22), Haiku subagents (#9), on-chain research (#10).
- Decisions D7 Merkle=jup distributor (SPL only), D8 ORAO VRF, D9 Streamflow lock,
  D10 vesting soft, D11 Grok builds engine, D12 free CLIs, D13 price unit.
- ENGINE_DESIGN v0.3: §8 epoch orchestrator spec.

## Open PRs
- none. Merged: #11 #23 #24 #27 #28 #30 #31 #33 #34 #35 #36 #37 #40 #41 #42.
- D14: unlock_twap_hours default 24h (§14 row 5 passes, margin 4.97% vs 5%).

## Grok queue (status:todo)
#26 epoch.py (unblocked, 2 PRs) · #43 sim --strict + TWAP sweep · #44 epoch file writer · #45 sim e2e (after #26)

## Open / blockers
- Claude Action errors on every @claude (#6, needs kiwi: app + token).
- Kiwi's GH token lacks `workflow` scope → workflow edits go through Grok.
- Main not protected (#7). Legal (#8) is kiwi's, not blocking engineering (D11).
- D6 conflict: this session runs Claude Code on the bot box with kiwi's GH token (kiwi's call).
- Top technical risk: Token-2022 mint ⇒ D7 rail doesn't work (#18).

## Next 3 actions (Claude)
1. Review #26 PRs line by line (money code). Then #45 e2e results vs §14.
2. Review #43 sweep: confirm 24h margin or move to 36h (D14).
3. #29 pad_rewards design (docs/design/PAD_REWARDS.md merged; needs kiwi before enabling; related-party flag -> #8).
