# STATE

last_tick: 2026-11-14 (interactive manager session, kiwi's account)
updated: 2026-11-14
phase: P1 decisions done → P2 engine build (Grok) + P3 sim harness

## Done
- P0 setup, CI (gitleaks fixed via #22), Haiku subagents (#9), on-chain research (#10).
- Decisions D7 Merkle=jup distributor (SPL only), D8 ORAO VRF, D9 Streamflow lock,
  D10 vesting soft, D11 Grok builds engine, D12 free CLIs, D13 price unit.
- ENGINE_DESIGN v0.3: §8 epoch orchestrator spec.

## Open PRs (Grok) — changes requested
- #23 draws: `split_prizes` float floor → Fraction + min(…, pot-paid).
- #28 rewards: allocate/split assert crash at budget ≥1e15 (1314/6000 repro) → clamp + Decimal sum + big-int tests.
- Merged this tick: #11 sybil, #24 ledger+twab, #27 scoring.

## Grok queue (status:todo)
#16 fees+vesting · #17 merkle · #18 Token-2022 research ·
#19 sim harness · #20 property suite + coverage gate · #25 hubs list · #26 epoch.py

## Open / blockers
- Claude Action errors on every @claude (#6, needs kiwi: app + token).
- Kiwi's GH token lacks `workflow` scope → workflow edits go through Grok.
- Main not protected (#7). Legal (#8) is kiwi's, not blocking engineering (D11).
- D6 conflict: this session runs Claude Code on the bot box with kiwi's GH token (kiwi's call).
- Top technical risk: Token-2022 mint ⇒ D7 rail doesn't work (#18).

## Next 3 actions (Claude)
1. Re-review #23/#28 when Grok pushes; merge on green.
2. Review #16/#17 PRs line by line (money code). #29 pad_rewards design (owner:claude, needs kiwi before enabling).
3. After #19 lands: spec remaining §14 scenarios (whale split, cap, underwater, pumps, bot).
