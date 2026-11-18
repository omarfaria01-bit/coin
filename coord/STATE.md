last_tick: 2026-11-18 ~10:25 Rome / 09:25 UTC (re-delivered 08:25/08:58 directives AGAIN verified on main: D35+D36 present, no dup PR; open PRs: only this state PR; Grok todo #257 #258, doing #249 #251; index-data last run still 08:39Z. Fixed stale wash row in #189 report: D35 removed round-trip filter, so wash volume works vs F10 (only F9 200 traders stops fake wallets); weights use raw volume at 50%, flag to kiwi. Next: review #249/#251/#257/#258 PRs; read next index-data output.)
prev_tick: 2026-11-18 ~10:20 Rome / 09:20 UTC (all 7 kiwi 08:25/08:58 points verified merged (D35, D36); no open PRs except this state PR. Grok doing #249 #251; queued #257 (INDEX_RULES<->params doc-sync test) and #258 (index read-only guard test) so 2 owner:grok todo exist. index-data last run still 08:39Z (members=0, F2 \$50k binds, question to kiwi in #1). Next: review #249/#251/#257/#258 PRs; read next index-data output.)
prev_tick: 2026-11-18 ~10:30 Rome (re-delivered 08:25/08:58 directives re-verified against main: D35+D36 merged (#238, #248), params.json has one keyword tier, no min_coverage/F6/overrides.allow, F1 4h, F4 8 SOL, F5 30%, weights mc_volume_capped 25%; full pytest green; no dup PR. Open PRs: only this state PR. Grok doing #249 #251. index-data last run still 08:39Z members=0 (F2 $50k binds, question to kiwi in #1). Next: review #249/#251 PRs; read next index-data output.)
prev_tick: 2026-11-18 ~10:15 Rome / 09:15 UTC (merged #255 = #247 history cache, CI green, 332 lines. Open PRs: none. Grok doing #249 (D36 golden) and #251 (F2 report). index-data last run still 08:39Z (members=0); Hetzner self-pulls #255 on next run, then check hourly run time < 10 min. Remaining owner:claude work needs kiwi (F2 question in #1, #168, #7) or live samples. Next: review #249/#251 PRs; read the next index-data output.)
prev_tick: 2026-11-18 ~10:20 Rome (D36 weights mc_volume_capped 25% MERGED #248: all 7 kiwi 08:25/08:58 points done; #244 #246 merged; Grok todo #247 #249; F2 question to kiwi still open)
prev_tick: (main 09:58) closed stale state PR #253; Grok #247 doing, #249 #251 todo
prev_tick: 2026-11-18 ~10:10 Rome (D36 weights mc_volume_capped 25% in PR; #244 #246 merged; Hetzner must pull /opt/coin after merge; F2 question to kiwi still open)
prev_tick: 2026-11-18 ~09:45 Rome (first D35 run 08:00Z: members=0, excluded=96 = 67 insufficient_data (no DexScreener liquidity), 28 F2, 1 F4. Only 36/233 sampled mints have liquidity, 12 >= $10k. F2 $50k now the binding filter; asked kiwi in #1 (a/b/c), NOT changing F2. Run still ~40 min.)
prev_tick: 2026-11-18 ~09:02 Rome (this session runs ON the Hetzner box: /opt/coin already at D35 code f33e3d4, the job script self-pulled at 08:46 CET; the 07:46Z output was from the run that started before the pull. 09:00 CET hourly run started on D35 code; no manual start needed. Waiting for its output on index-data. Weights: waiting for kiwi.)
prev_tick: 2026-11-18 ~09:56 Rome (no code change possible: index-data last run still 07:46Z = Hetzner has NOT pulled D35; open PRs only state PR; Grok todo #239 #240 queued; weights waiting for kiwi; #189 rest/#169/#172 need kiwi or live data)
prev_tick: 2026-11-18 ~09:15 Rome (no open PRs; Grok todo #239 #240 queued. Hetzner has NOT pulled D35 yet: index-data last run 07:46Z still on code ad29161 with old rules (reason 'weak_keyword' in output). Samples live only on Hetzner (data/index/samples, not in git), so no top-10 can be produced from here. Blocker = Grok executor runs the D35 ACTION below. Weights: still waiting for kiwi's choice.)
prev_tick: 2026-11-18 ~08:50 Rome (kiwi 08:25 rule changes DONE: D35 merged in #238 (one keyword tier, no min_coverage, F1 4h, F4 8 SOL, F5 30%, no F6, F10 volume>0; sampler own lock, 10 discover pages). Merged #234 #235 #236; closed #237/#231 (obsolete). Queued #239 #240 for Grok. Weights: WAITING for kiwi's choice (not changed). No open PRs.)
prev_tick: 2026-11-18 ~06:55 Rome / 04:55 UTC (URGENT seed directive re-verified again: index/seed_mints.txt 101 lines on origin/main, index-data last run 04:00Z, NO dup PR. Open owner:grok todo: #231 #232, doing: #224 #225. Nothing else startable by Claude; earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~06:40 Rome / 04:40 UTC (URGENT seed directive re-verified: index/seed_mints.txt on main, index-data last run 04:00Z, no dup PR, no open PRs. Opened #231 (coverage progress+ETA tool) and #232 (seeded mints vs filters Hypothesis) for Grok; #224 #225 doing. Earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~06:25 Rome / 04:21 UTC (URGENT seed directive re-verified: index/seed_mints.txt (101 lines, D30) on main, index-data last run 04:00Z, no dup PR, no open PRs. Open owner:grok todo: #224 #225. Nothing else startable; earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~05:20 Rome / 04:18 UTC (URGENT seed directive re-verified yet again: index/seed_mints.txt (101 lines, D30) on main, Hetzner index-data last run 04:00Z, no duplicate PR opened. #229 state PR green -> merged. Open owner:grok todo: #224 #225. Nothing else startable; earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~05:35 Rome / 04:35 UTC (seed already on main + Hetzner sampling, no dup PR. Merged #227 (#216 job-script contract tests) and #228 (#215 coverage table: 12h at 5min/0% miss, 13.3h @10% miss, 17.1h @30%; never slow the timer). Open owner:grok todo: #224 #225. Earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~05:15 Rome / 04:15 UTC (URGENT seed directive re-verified again: index/seed_mints.txt on main, Hetzner index-data last run 04:00Z, no dup PR. #189 attack replay merged (#223). No open PRs; owner:grok #215/#216 are doing, so queued #224 (output schema doc for front end) and #225 (hourly draw fairness sim). Earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~06:10 Rome (urgent seed already on main + Hetzner sampling, no dup PR; started #189: hourly attack replay tests+report in PR; open prs only this one)
prev_tick: 2026-11-18 ~05:30 Rome / 04:30 UTC (URGENT seed directive re-verified: index/seed_mints.txt (101 lines, D30) already on main, Hetzner pulled, index-data last run 04:00Z; no duplicate PR. No open PRs; #215 #216 owner:grok todo queued. #172 done up to what needs no kiwi (D34); basket-buy TWAP/private path = mainnet design, needs kiwi. Nothing else startable until ~12h coverage, earliest non-empty top-10 ~15:00Z)
prev_tick: 2026-11-18 ~05:05 Rome / 04:05 UTC (seed PR still NOT needed: index/seed_mints.txt on main. Hetzner HAS pulled: index-data has 03:00Z+04:00Z runs on code c6c0ca8 covering 99 seed mints, all insufficient_data until ~12h of samples (earliest non-empty top-10 ~15:00Z). No open PRs; queue #215 #216 owner:grok todo)
prev_tick: 2026-11-18 ~05:00 Rome (urgent seed directive re-checked again: index/seed_mints.txt (101 lines, D30) is on main, no duplicate PR; merged #218 (emergency_reason Hypothesis, CI green); index-data last push still 02:51Z = Hetzner pull STILL pending, Grok executor must run the ACTION below)
prev_tick: 2026-11-18 ~05:15 Rome (seed PR was already on main -> no duplicate opened; merged #211 (F11/F8c Hypothesis) and #213 (fixed stale F9 assertion on branch, CI green); index-data STILL last push 02:51Z = Hetzner pull pending)
prev_tick: 2026-11-18 ~04:45 (seed verified on main)
prev_tick: 2026-11-18 ~06:30 (#172 D34 in PR); before: 05:30 Rome (seed universe #199 already merged; #202 merged; #170 F9/F10 = D33 in PR; next #172, #189)
updated: 2026-11-17
phase: P2 engine rewrite to COIN_MATH v0.3.3 (Grok slices) → wiring → P3 sim table + variant report for kiwi
parallel: #156 GTA 6 Index (kiwi, 17 Nov) — cloud Claude session is temporary manager for it while Grok is offline; Hetzner Claude session owns site + daily job. Brief: docs/prompts/PROMPT_INDEX.md. Out of scope: vesting/locks (D24).

## Overnight backend checklist (kiwi directive 18 Nov 02:10 Rome, target 09:00 Rome)
- [x] 1. Stacked PRs #176–#185 reviewed and merged (bottom-up; #184 rebased, #185 cherry-picked onto main and cut to 240 lines).
- [x] 2. kiwi's #156 decisions recorded and implemented: D26 (GTASP10, Helius, pump.fun, 70/30, hourly rebalance), D27 (T_START 1h, 5x curve at 4h, #192), D28 (hourly draw: cap 5%, sqrt odds, min pot rollover, 70/30 fees, no team/buyback, #195). Draws stay OFF (legal #8). Flipper row bound 30%→60% flagged to kiwi.
- [x] 3a. #163 hourly job merged with #185 (dry-run only; server install is separate). [~] 3b. #189 sim/Hypothesis coverage: slice 1 (cheap top-10, wash, sybil, hysteresis, curve, hourly draw) in PR; basket sandwich + cluster sybil left (#172/#169). [ ] 3c. #167/#169/#170/#171/#172 rule hardening (docs, next).
- [~] 4. Dry-run top-10: ran read-only, 0 candidates (pump.fun history = ~1s/page). Report reports/index_dryrun_2026-11-18.md; question to kiwi in #196.
- [x] 5. Grok queue: #193, #194 opened (owner:grok, status:todo).
- [x] 3c-partial. #167 F11, #169 F5 (D31), #171 F8c (D32, #203) merged. #170 F9/F10 (D33, funding-cluster part left). Left: #171 F8b (needs live mint check), #169 F1/F3/F6/F7, #172.
- [ ] 3d. Left, not startable by Claude alone: #169 F1 48h/72h (kiwi picks) and creator-cluster F3/F6/F7 (needs first-funder collector, large); #189 sim coverage (Grok #205/#206/#209 cover parts; rest = report update of #162 table for hourly schedule).
- [ ] 6. Skipped: #186 (needs workflow-scope token), #168 and #7 (needs:kiwi).

## D35 on Hetzner — DONE (09:00 Rome)
/opt/coin is at D35 code (self-pulled by index-job.sh). First D35 hourly run started 09:00 CET. No executor action needed; check index-data for the 08:00Z output (members/excluded counts).

## (old) ACTION FOR GROK EXECUTOR (Hetzner) — DONE 2026-11-18 (runs 03:00Z/04:00Z on index-data, code c6c0ca8 has the seed). Keep timers running.
After the seed-universe PR (#196 follow-up, D30) merges: the job script does `git pull --ff-only origin main` itself on the next run, but run once by hand to start sampling now: `cd /opt/coin && git pull --ff-only origin main && systemctl start coin-index-sample.service`. Optional env: `COIN_INDEX_DISCOVER_PAGES` (default 100). Coverage ~12h of 5-min samples is still needed before a non-empty top-10.

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
-9. 2026-11-18: #188 and #187 (Bandit fixes, Grok-account issues, small) implemented and merged by Claude. Remaining owner:claude: #186 (CI scanners; workflow edits need Grok/kiwi token scope), #189 (index sim coverage, wait for #176-#185), index docs #167-#172.
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

## ACTION FOR GROK EXECUTOR (Hetzner) after D36 (#248)
`cd /opt/coin && git pull --ff-only origin main` (the job script also self-pulls). Grok todo: #247 (history cache, hourly < 10 min), #249 (D36 golden). Open question to kiwi in #1: F2 $50k binds (only 12 of 233 mints >= $10k liquidity).
