last_tick: 2026-11-15 UTC (merged #50 D15 after kiwi APPROVED #50 from his own login; no open PRs; open: #29 held for kiwi/legal #8, #7 needs kiwi; main CI green)
updated: 2026-11-14
phase: P2 engine rewrite to COIN_MATH v0.3.3 (Grok slices) → wiring → P3 sim table + variant report for kiwi

## Done
- P0 setup, CI, Haiku subagents, on-chain research. D7–D14 (see DECISIONS; D2/D4/D13/D14 superseded by D16).
- v0.3.3 spec merged (#62). Engine slices merged: eligibility #68, hold curve #69, score over lots #80,
  vesting #75, sybil first slice #76, cap G=2 #77, draws #78. Tooling #57 #59 #63.
- Closed as obsolete: #56 #58 #61 (+ issues #52 #54).

## Open PRs
- #64 auto-review workflow: merged (pull_request_target, review-only perms). #117 v0.2 float deletion merged.
- #60 runbook: HOLD until wiring merges (v0.2 content).
- #50 D15 router: kiwi APPROVED 2026-11-14 20:28Z; merged (conflict with D16+ resolved).
- Merged: #110 golden (#83), #112 §14 rows (#84 step 1), #108 §11 price unlock (D20), #107 launch flags off (D19). #114 (#84 attack rows) and #116 (#84 step 3a population) merged. #111 exact budget+TWAB (#82 4b; #107 retargeted to main but CONFLICTS — Grok to rebase #107→#108→#110 in order, asked on #82). #105 balances §13 + balances.json (#82 4a). #106 auto-closed by branch delete; Grok to reopen vs main, #107/#108 to be retargeted (asked on #82). #103 wiring sybil v0.3.3 + soft vesting (#82 PR3/4), #101 wiring scoring+cap+exact payout (#82 PR 2/4), #99 sybil L4-L6+hubs, #97 sybil strong+merge rule, #93 prices, #96 events (#93 fixed + split), #91 fee routing v0.3.3, #94 soft vesting forfeit. Earlier: #70 balances (pull-back fixed), #87 exact payout, #88 params, #89 ledger v0.3.3, #90 no-float ratchet.

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
-2. Tick 04:30 UTC: #131 merged (runbook v0.3.3, #55 closed), #60 closed. Grok queue empty; nothing owner:grok/status:todo open. Waiting on kiwi: #50 APPROVED, #7, #85 variant choices.
-1. Tick 21:20 UTC: open PRs are only #60 (HOLD) and #50 (needs kiwi). T_START=6h = D21, already default+goldens (#123). #84/#85 closed, #127 merged, main CI green. All #81/#82 slices are merged; Grok to post final acceptance evidence on #81/#82 (conservation, no-float CI, coverage) so they can close.
0. #118 (#84 step 3b report writer) and #119 (#85 variants, default T_START=6h, report regenerated) merged. #85 done; kiwi summary in reports/variants_v033_2026-11-14.md, announced in #1.
1. #84: report regenerated on main (3 seeds, deterministic): 27 PASS · 0 FAIL · 19 GAP (GAPs are documented: boost/draws/bot off per D19, ingest-layer rows). Committed report was stale (pre-T_START=6h). Close #84 once refresh PR merges. #82 wiring (PR 3/4, 4/4: #103/#101 etc.) and #81 remaining slices continue.
2. #60 runbook: hold lifted, Grok reworking via #55 (v0.3.3). If no PR in 3h, rework it myself. #50 needs kiwi's APPROVED.
3. Await kiwi's choices on #85 variants (recommendation: keep curve and MIN_ELIGIBLE_SHARE; draws unchanged); record in DECISIONS.
Also: #29 pad_rewards (needs kiwi before enabling; related-party flag -> #8). Top risk unchanged: Token-2022 mint (#18).
