# STATE

last_tick: 2026-11-14 (interactive manager session; merged #23 #28 #30 #31)
updated: 2026-11-14
phase: P1 decisions done → P2 engine build (Grok) + P3 sim harness

## Done
- P0 setup, CI (gitleaks fixed via #22), Haiku subagents (#9), on-chain research (#10).
- Decisions D7 Merkle=jup distributor (SPL only), D8 ORAO VRF, D9 Streamflow lock,
  D10 vesting soft, D11 Grok builds engine, D12 free CLIs, D13 price unit.
- ENGINE_DESIGN v0.3: §8 epoch orchestrator spec.

## Open PRs (Grok)
- #32 sim CLI + sniper/flipper: code OK, but auto-closed (base branch deleted after #31 squash). Grok to rebase onto main and open a NEW PR (comment on #19).
- Merged: #11 sybil, #24 ledger+twab, #27 scoring, #23 draws, #28 rewards, #30 merkle (byte-exact vs jup vectors), #31 sim market/agents.

## Grok queue (status:todo)
#16 fees+vesting · #18 Token-2022 research · #19 re-PR (rebase) ·
#20 property suite + coverage gate · #25 hubs list · #26 epoch.py

## Open / blockers
- Claude Action errors on every @claude (#6, needs kiwi: app + token).
- Kiwi's GH token lacks `workflow` scope → workflow edits go through Grok.
- Main not protected (#7). Legal (#8) is kiwi's, not blocking engineering (D11).
- D6 conflict: this session runs Claude Code on the bot box with kiwi's GH token (kiwi's call).
- Top technical risk: Token-2022 mint ⇒ D7 rail doesn't work (#18).

## Next 3 actions (Claude)
1. Review new #19 PR (sim CLI) → merge on green. Then spec remaining §14 scenarios (whale split, cap, underwater, pumps, bot).
2. Review #16/#26 PRs line by line (money code). #18 result decides D7 viability (Token-2022).
3. #29 pad_rewards design doc (owner:claude, needs kiwi before enabling; related-party flag → #8).
