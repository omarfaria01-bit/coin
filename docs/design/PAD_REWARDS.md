# `pad_rewards` extension point (design only)

Draft input for issue #29 (owner: Claude). This document is **not** an accepted
ADR and must not be copied into `coord/DECISIONS.md` without Claude's triage
and kiwi's later approval. No engine code ships with this draft.

Opened by Grok while Claude was rate-limited; please triage.

## 1. Purpose

The engine must stay pad-agnostic (`config/pad.json`, COIN_MATH §15). The
launchpad is owned by an acquaintance of kiwi, is **not built yet**, and its
features are **unknown**. We must not invent pad mechanics or deal terms.

If that pad later offers its own rewards or hooks, we want a disabled-by-default
extension point — `pad_rewards` — so we can plug them in without touching core
math (scoring, clustering, the whale cap, `allocate` / `split_to_wallets`,
draws, claims).

Until the pad is actually known, D7–D10 and any pad-tied reward ideas stay
parked. The hook exists so the *shape* of a later plug-in is agreed; it does
not implement one.

## 2. Non-goals

- No speculative logic in `engine/`. This PR is documentation only.
- No contact with the pad owner, no deal terms, no on-chain action.
- No change to committed `config/coin.json`, `config/pad.json`, or JSON schema
  in the accompanying PR. Config below is a **proposal** for a later code issue,
  after Claude triages #29.
- No edit of `coord/DECISIONS.md` or `coord/STATE.md`.
- No enabling of the hook. Enabling is a later, gated decision (section 6).

## 3. Proposed interface

A single pure function (or a `Protocol` with one method) evaluated *after* the
epoch snapshot is already computed, and *never* in the opposite direction.

The hook may only return **informational annotations**. The engine must not
feed those annotations back into `capped_shares`, `allocate`, draws, or
claims.

```python
from collections.abc import Mapping
from typing import Protocol

from engine.types import ClusterId, WalletId


class EpochSnapshot(Protocol):
    """Already-computed epoch result. Treated as immutable by the hook."""

    budget: int                    # R_e, lamports
    payouts: Mapping[WalletId, int]
    cluster_payouts: Mapping[ClusterId, int]
    rollover: int
    dust: int
    scores: Mapping[ClusterId, float]
    shares: Mapping[ClusterId, float]
    cluster_of: Mapping[WalletId, ClusterId]


class PadRewardsConfig(Protocol):
    enabled: bool  # default False


class PadRewardsAnnotation(Protocol):
    """Sidecar only. Must never be applied as a payout delta inside engine/."""

    notes: Mapping[str, str]  # free-form, keys = wallet or cluster ids
    # Optional suggestions for an *off-engine* system (points, allowlists).
    # The engine ignores these when writing claims / push lists.
    suggested_off_engine: Mapping[str, str]


def pad_rewards(
    snapshot: EpochSnapshot, config: PadRewardsConfig
) -> PadRewardsAnnotation:
    """Pure: no I/O, no wall clock, no network, integer money only if any
    amounts appear in annotations (and even then they are not paid by the engine).
    """
    ...
```

When `config.enabled` is false, or when no hook is registered, the function
is a no-op and the epoch result is byte-identical to today's output.

### Must not

- Change `budget`, `payouts`, `cluster_payouts`, `shares`, `rollover`, or `dust`.
- Break conservation: `sum(payouts) + rollover + dust == budget` remains an
  engine invariant, enforced *outside* the hook and independent of its return
  value.
- Grant per-wallet special treatment that bypasses sybil clustering or the
  whale cap (no “this wallet gets +x because the pad said so” inside `allocate`).
- Perform I/O, read the clock, or call RPCs. If a later pad integration needs
  external data, that data is supplied as an already-materialized, committed
  input to the epoch (like any other snapshot field), never fetched inside
  `engine/`.

If a hook return is malformed, the engine rejects it and proceeds as if the
hook were disabled (or fails the epoch closed-loop test). It must not apply a
partial or guessed adjustment.

## 4. Proposed config shape (not committed here)

`config/pad.json` is already the unfilled pad template (COIN_MATH §15; unknown
keys rejected). A later schema change, if accepted, would add a nested object
without colliding with existing keys:

```json
{
  "pad_rewards": { "enabled": false }
}
```

Absence of the object is equivalent to `enabled: false`. The default committed
config stays off. Enabling requires the gate in section 6, not a silent default
flip.

Whether this lives on `pad.json` or `coin.json` is an open question for #29.
`pad.json` is the more natural home (pad-specific, still empty today).

## 5. Cross-reward options (discussion only)

These are options that *might* appear once the pad exists. None is chosen.
Until the pad is known, the recommendation is the same for all four: **keep
them off-engine**.

| Option | What it would mean | Where it should live | Risks | Recommendation |
|---|---|---|---|---|
| Fee discounts | Our holders pay lower pad trading or launch fees | Pad-side (their fee schedule / UI) | Low for our engine if we never rebate out of `R_e`. Sybil risk *on the pad* if discounts are per-wallet without clustering | Off-engine. At most, the hook may annotate “this clustered entity was a holder at `t1`” for the pad to consume |
| Early access | Priority / allowlist for a pad sale | Pad-side allowlist, possibly fed by a published snapshot (e.g. a merkle root we already produce for claims) | Farming via wallet splits if the pad keys off raw wallets instead of clusters | Off-engine. Reuse an already-published snapshot; do not add a second, weaker eligibility path in the engine |
| Points | Loyalty points credited by the pad | Off-engine points ledger | Low engine risk if informational. High risk if points are later converted into extra `π` or extra lamports inside `allocate` | Off-engine. Hook annotations may *suggest* credits; the engine must not pay them |
| Fee-share | A fraction of pad-side fees is shared with our holders | A **separate** pot, if it ever exists, with its own conservation identity, funded from pad-side accounts | **Severe** if commingled with the holder pot: `sum(payouts)+rollover+dust == R_e` would no longer be about *our* budget alone, and pad inflows could become a hidden related-party subsidy | Never mix pad fee-share into `R_e`. If a share is ever approved, it is a distinct budget with its own ADR, sim re-run, and legal review |

No option above authorizes a change to clustering, the cap, draws, or vesting.

## 6. Enablement gate

`enabled: true` is forbidden until **all** of the following exist:

1. The pad is actually specified (real `pad.json` fields, not a guess).
2. An ADR in `coord/DECISIONS.md`, written and accepted under the normal
   decision process (not this draft).
3. A simulator re-run of the COIN_MATH §14 suite (and any new pad-specific
   cases) with the hook registered and with it disabled; disabled must remain
   byte-identical to the pre-hook baseline.
4. kiwi **APPROVED**.
5. Legal / disclosure review under COIN_MATH §16 and issue #8. A pad owned by
   a connection of kiwi can look like a related-party or hidden-incentive
   arrangement. That is a kiwi + counsel question, not an engineering one.

This document does not start that legal work and does not assume its outcome.

## 7. Test plan (for a later implementation issue, not this PR)

- Config absent, and config present with `pad_rewards.enabled=false`, both
  produce bit-for-bit the same `EpochResult` / claims document as today
  (`inputs_hash` included).
- A hook that returns annotations does not change `payouts`, `rollover`,
  `dust`, `shares`, or claims bytes.
- A hook that attempts to smuggle payout deltas is rejected; conservation
  still holds.
- Annotations cannot raise any cluster's `π` above `CAP` because they cannot
  change `π`.
- Unknown config keys still rejected by the existing params/schema strictness.

## 8. Open questions for Claude / kiwi

1. Should `pad_rewards` live on `pad.json` or `coin.json`?
2. Should annotations be a sidecar artifact next to `epochs/<n>/`, or a
   field on `EpochResult` that is explicitly excluded from claims / push?
3. How would a future pad verify “was a holder at `t1`” without pulling I/O
   into `engine/`? (Candidate: reuse the claims merkle root or a published
   cluster snapshot.)
4. If fee-share is ever desired, who custodials the separate pot, and does
   #8 require public disclosure before that pot is filled?
5. Confirm that this draft, if useful, should be folded into ENGINE_DESIGN
   (a short `pad_rewards` section) under #29 rather than living as a
   standalone file forever.

## 9. Draft provenance

- Constraints taken from issue #29, the launchpad correction on issue #1, and
  COIN_MATH §15–§16.
- A first prose pass was produced with Gemini CLI (`gemini --skip-trust -p`,
  2026-11-14, Europe/Rome) and then checked and rewritten by Grok. An
  OpenCode free-model pass was started for a second opinion but did not return
  a usable document in time; this text is the verified version, not a raw
  model dump.
