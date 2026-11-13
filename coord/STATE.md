# STATE

last_tick: never
updated: 2026-11-14 (session 1, interactive)
phase: P0 Setup → P1 Spec freeze

## Done
- Repo created (private), spec v0.2, prompts, labels, CONTROL ROOM (#1), G0 for Grok (#2).
- Skeleton: pyproject (uv), typed config + JSON schemas, engine stubs with signatures,
  docs/ENGINE_DESIGN.md, CLAUDE.md, CI (ruff, pytest, schema check, gitleaks), Claude workflow.

## Open / blockers
- Claude Action inactive until kiwi installs the Claude GitHub App + adds CLAUDE_CODE_OAUTH_TOKEN (needs:kiwi issue).
- `main` not technically protected (free private repo): "only Claude merges" is a rule, not a guarantee (needs:kiwi issue).
- Legal review (COIN_MATH §16) not started (needs:kiwi issue).
- Coverage gate (≥ 90% on engine/) not enforced yet: enforce once P2 modules land.
- First tick must verify that `gh` is authenticated inside the Action (GH_TOKEN env set).

## Grok queue
- #2 G0 toolchain · P1 research · P2 sybil.py · P2 draws.py

## Next 3 actions (Claude)
1. Once the Action works: review Grok's P1 research, pick distributor/VRF/lock in DECISIONS.md.
2. Write ledger.py + twab.py with tests (P2).
3. Write scoring.py + rewards.py with property tests (P2).
