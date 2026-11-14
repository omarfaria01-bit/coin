# STATE

last_tick: 2026-11-14 (manager session: merged #33-#37 #40 #41 + D14 PR #42)
updated: 2026-11-14
phase: P1 decisions done → P2 engine build (Grok) + P3 sim harness

## Done
- P0 setup, CI (gitleaks fixed via #22), Haiku subagents (#9), on-chain research (#10).
- Decisions D7 Merkle=jup distributor (SPL only), D8 ORAO VRF, D9 Streamflow lock,
  D10 vesting soft, D11 Grok builds engine, D12 free CLIs, D13 price unit.
- ENGINE_DESIGN v0.3: §8 epoch orchestrator spec.

## Open PRs
- none. Merged: #11 #23 #24 #27 #28 #30 #31 #33 #34 #35 #36 #37 #40 #41 #42. Main: 96% engine coverage.

## Grok queue (status:todo)
#26 epoch.py (unblocked) · #43 sim strict+vesting sweep · #44 epoch artifact writer · #45 sim e2e (after #26)

## Open / blockers
- Claude Action errors on every @claude (#6, needs kiwi: app + token).
- Kiwi's GH token lacks `workflow` scope → workflow edits go through Grok.
- Main not protected (#7). Legal (#8) is kiwi's, not blocking engineering (D11).
- D6 conflict: this session runs Claude Code on the bot box with kiwi's GH token (kiwi's call).
- Top technical risk: Token-2022 mint ⇒ D7 rail doesn't work (#18).

## Next 3 actions (Claude)
1. Review #26 PRs line by line (money code). Then #44, #45.
2. D14 margin thin (4.97% vs 5%): act on #43 sweep result (maybe 36h).
3. #29 pad_rewards design reviewed -> needs kiwi before enabling (related-party -> #8). #18 result: Token-2022 mint => push rail (kiwi/pad choice open).
