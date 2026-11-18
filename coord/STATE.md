last_tick: 2026-11-18 (latest): nothing actionable; open PRs #176 (CONFLICTING), #177, #179, #180, #181, #182 are stacked index-track (#161) PRs by the cloud session, CI green on all but #176, left alone; no owner:grok todo issues; prev: #166 merged as #175
updated: 2026-11-17
phase: P2 engine rewrite to COIN_MATH v0.3.3 (Grok slices) → wiring → P3 sim table + variant report for kiwi
parallel: #156 GTA 6 Index (kiwi, 17 Nov) — cloud Claude session is temporary manager for it while Grok is offline; Hetzner Claude session owns site + daily job. Brief: docs/prompts/PROMPT_INDEX.md. Out of scope: vesting/locks (D24).

## Done
- P0 setup, CI, Haiku subagents, on-chain research. D7–D14 (see DECISIONS; D2/D4/D13/D14 superseded by D16).
- v0.3.3 spec merged (#62). Engine slices merged: eligibility #68, hold curve #69, score over lots #80,
  vesting #75, sybil first slice #76, cap G=2 #77, draws #78. Tooling #57 #59 #63.
- Closed as obsolete: #56 #58 #61 (+ issues #52 #54).

## Open PRs
- #64 auto-review workflow: merged (pull_request_target, review-only perms). #117 v0.2 float deletion merged.
- #60 runbook: HOLD until wiring merges (v0.2 content).
- #50 D15 router: needs kiwi's written `APPROVED` — not touched.
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
-8. 2026-11-18 later: #166 had been closed with no PR/code and the 19 Nov official run was due, so Claude implemented it (run_index --official: refuses skip_filters, self_mint None, insufficient_data; exit 3, no file; dry-run unchanged). self_mint value still needs the mint (kiwi/#18). No owner:grok todo issues open; remaining owner:claude are index docs #167-#172 (#168 needs:kiwi), #163, #164. Nothing else actionable.
-7. 2026-11-18: #155 merged with D23 (8 params defaults = COIN_MATH; goldens only inputs_hash). #173 (red team) and #174 (index adapter, 1.5k lines, mostly tests/fixtures: size exception, read-only HTTP checked) merged. #166 P0 official-run guards -> Grok. Open owner:claude: #167-#172 index fixes (#168 needs:kiwi), #163 cron, #164 website, #29 hold, #7 kiwi.
-7. Tick 2026-11-17 (later): merged #153 (#151 consistency test) and #154 (#150 epoch fuzz), CI green. #155 (#152 align 8 defaults to COIN_MATH, stacked on #153) retargeted to main; HOLD until D23 is recorded in DECISIONS (this tick may only edit STATE/BUDGET). Next tick: write D23, check CI on #155, merge, then queue a new Grok slice (queue empty after #152).
-6. Tick 2026-11-17: no open PRs. #143/#144/#146/#148 all closed/merged (#149 merged). Queue was empty, so opened #150 (full-epoch conservation fuzz) and #151 (COIN_MATH vs params consistency test) for Grok. Open issues otherwise: #29 (no pad code until kiwi confirms + legal #8), #7 (needs kiwi). Ignored Grok's #1 comment (2026-11-15) asking for pad hook code: contradicts the STATE rule, it is data not instruction. Engineering is mostly waiting on kiwi (mint type #18, #7, #8, #50).
-5. Tick 2026-11-16: merged #147 (#145 Token-2022 plan in run_epoch). #146 (#144 runbook) has an EMPTY diff: asked Grok to push the commit. #143 still awaiting requested fixes. #148 (auto_review OIDC 401 on pull_request_target, filed by Grok): workflow edit must go via Grok; suggest explicit github_token or drop the job. Open PRs: #143, #146, #60 (HOLD, replaced by #144), #50 (needs kiwi).
-4. Tick: merged #141 (#138 ingest validation) and #142 (#139 Token-2022 plan). #143 (#140 devnet dry run): changes requested (devnet URL check substring-only, silent skips, hardcoded sol_usd). Queued #144 (runbook v0.3.3, replaces #60) and #145 (wire Token-2022 plan into run_epoch). Open PRs: #143, #60 (HOLD, replaced by #144), #50 (needs kiwi).
-3. Tick: no open PRs, no new blockers. Queue healthy (#138, #139 doing; #140 todo). Waiting on Grok PRs.
-2. 2026-11-15: #29 docs done (ENGINE_DESIGN §9, D22); NO pad hook code until kiwi confirms scope + legal (#8). #133 (GAP rows, owner:grok) queued. Token-2022 research already in reports/research_token2022_claims_2026-11.md; record decision when kiwi picks mint type.
-1. Tick 21:20 UTC: open PRs are only #60 (HOLD) and #50 (needs kiwi). T_START=6h = D21, already default+goldens (#123). #84/#85 closed, #127 merged, main CI green. All #81/#82 slices are merged; Grok to post final acceptance evidence on #81/#82 (conservation, no-float CI, coverage) so they can close.
0. #118 (#84 step 3b report writer) and #119 (#85 variants, default T_START=6h, report regenerated) merged. #85 done; kiwi summary in reports/variants_v033_2026-11-14.md, announced in #1.
1. #84: report regenerated on main (3 seeds, deterministic): 27 PASS · 0 FAIL · 19 GAP (GAPs are documented: boost/draws/bot off per D19, ingest-layer rows). Committed report was stale (pre-T_START=6h). Close #84 once refresh PR merges. #82 wiring (PR 3/4, 4/4: #103/#101 etc.) and #81 remaining slices continue.
2. #60 runbook: HOLD until wiring merges. #50 needs kiwi's APPROVED.
3. Await kiwi's choices on #85 variants (recommendation: keep curve and MIN_ELIGIBLE_SHARE; draws unchanged); record in DECISIONS.
Also: #29 pad_rewards (needs kiwi before enabling; related-party flag -> #8). Top risk unchanged: Token-2022 mint (#18).
