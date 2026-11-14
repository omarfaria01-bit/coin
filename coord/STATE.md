last_tick: 2026-11-14 (manager loop; merged #97 sybil S1-S3/L1-L3; #99 needs rebase)
updated: 2026-11-14
phase: P2 engine rewrite to COIN_MATH v0.3.3 (Grok slices) → wiring → P3 sim table + variant report for kiwi

## Done
- P0 setup, CI, Haiku subagents, on-chain research. D7–D14 (see DECISIONS; D2/D4/D13/D14 superseded by D16).
- v0.3.3 spec merged (#62). Engine slices merged: eligibility #68, hold curve #69, score over lots #80,
  vesting #75, sybil first slice #76, cap G=2 #77, draws #78. Tooling #57 #59 #63.
- Closed as obsolete: #56 #58 #61 (+ issues #52 #54).

## Open PRs
- #64 auto-review workflow: CHANGES REQUESTED (pull_request secret exposure, perms, merge authority).
- #60 runbook: HOLD until wiring merges (v0.2 content).
- #50 D15 router: needs kiwi's written `APPROVED` — not touched.
- #99 sybil L4-L6: reviewed OK, CONFLICTS after #97 squash → Grok to rebase onto main.
- Merged: #97 sybil strong+merge rule, #93 prices, #96 events (#93 fixed + split), #91 fee routing v0.3.3, #94 soft vesting forfeit. Earlier: #70 balances (pull-back fixed), #87 exact payout, #88 params, #89 ledger v0.3.3, #90 no-float ratchet.

## Grok queue (status:todo)
#81 remaining engine slices · #82 wire v0.3.3 into epoch.py (blocked by #81 steps 1–3) · #83 goldens ·
#84 §14 acceptance table · #85 variant comparison for kiwi. Fixes for #70 and #64 first.

## Open / blockers
- Claude Action errors on every @claude (#6, needs kiwi: app + token).
- Kiwi's GH token lacks `workflow` scope → workflow edits go through Grok.
- Main not protected (#7). Legal (#8) is kiwi's, not blocking engineering (D11).
- D6 conflict: this session runs Claude Code on the bot box with kiwi's GH token (kiwi's call).
- Top technical risk: Token-2022 mint ⇒ D7 rail doesn't work (#18).

## Next 3 actions (Claude)
1. Merge #99 once rebased (CI green); re-review #64 after Grok's fix; review remaining #81 slices.
2. Review wiring PRs (#82); check conservation and no-float CI check.
3. When #85 lands: summarize in Italian for kiwi (#1) and record his parameter choices in DECISIONS.
Also: #29 pad_rewards (needs kiwi before enabling; related-party flag -> #8). Top risk unchanged: Token-2022 mint (#18).
