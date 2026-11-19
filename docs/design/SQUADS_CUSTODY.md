# Custody proposal: Squads v4 multisig + spending limit (#342 B, #348 B3)

Status: **write-up only. No code, no custody change, no mainnet action without kiwi's `APPROVED`.**

## Today

One hot wallet (`3ann…hJkd`) gets 100% of the creator fees and holds everything: the SOL prize pot
(28%, it only grows while the draw is off), the reserve, the rent float and the basket coins until the
daily payout. Its key is on the server (`/etc/coin/fee-bot/keypair.json`, 600, `coinbot`). The caps in
`econ/params.json` (D50) bind **our bots**, not someone who steals the key: a stolen key can empty the
wallet in one transaction. Hardening (`docs/runbooks/server_hardening.md`) lowers the odds, not the loss.

## What Squads v4 gives

- A **multisig vault**: moving funds needs a proposal approved by a threshold of member keys.
  Optional **time lock**: an approved proposal waits N seconds before it can execute.
- A **spending limit**: a pre-approved allowance for named members, one token mint per limit, an
  amount that resets each period (one-time, day, week, month), and an optional list of allowed
  destinations. A member spends under it **without** a proposal or the time lock. It is created, changed
  or removed only by a config transaction approved by the multisig.
- `spending_limit_use` only **transfers** SOL or one SPL/Token-2022 mint from the vault to a destination
  (the destination's token account must already exist). It cannot run a Jupiter swap, a pump.fun claim
  or a payout batch.

## Consequence for our design

Swaps and payouts cannot run "through" the spending limit, and claims need the fee recipient to sign.
So the workable shape is **cold vault + small hot wallet**:

1. Fees keep arriving in the hot wallet `3ann…` (the bot claims them as today; the pump.fun recipient
   does not change).
2. Every fee-bot run, after the split and the basket buys, the hot wallet **sweeps** the pot slice and
   any SOL above a ceiling (reserve + rent float + one day of basket budget) to the Squads vault.
   A sweep is a plain transfer *into* the vault: no Squads instruction needed.
3. The vault gives the bot key one **SOL spending limit**: period = day, amount = what the hot wallet
   may need per day (rent top-up; later the draw prize), destinations = [`3ann…`] only.
4. Basket coins stay in the hot wallet until the daily payout (≤ 1 day of buys). A spending limit per
   basket mint is not practical: members change every hour.
5. Multisig time lock **72h** on everything else, matching D50: any move by the signers out of the vault
   is public on-chain 3 days before it can execute.

**Worst case with a stolen server key:** hot wallet balance (≤ one day of flow + reserve + rent float,
bounded by the bot's day cap, today 20 SOL) **plus** one day of the spending limit. The pot in the vault
is safe. Today the worst case is everything.

**What it does not fix:** the fee recipient stays the hot key. If that key is stolen, future fees go to
an address the thief controls until the recipient is changed. D45 says the recipient is set once and
then locked: before any rollout, check on devnet whether pump.fun fee sharing can be pointed at a
new wallet later, and by whom (if the vault can be the fee-sharing admin, the multisig can rotate a
stolen key out).

## Cost (from the Squads docs; check the app at the time)

| Item | SOL |
|---|---|
| Multisig deployment fee (one time) | 0.1 (the docs' figure; the app may show less) |
| Squads account funding + account rent | ~0.001 + ~0.0018 |
| Create one spending limit | ~0.0076 |
| Create a time lock (config change) | ~0.0069 |
| Each proposal (vault move, config change) | network fees + rent, rent reclaimable after execution |
| Hourly sweep into the vault | one normal transfer fee |

About **0.12 SOL** to set up, near zero to run.

## Steps (each needs kiwi; nothing here is approved)

1. Devnet first: create a 2-of-3 multisig, add the spending limit and the 72h time lock, run the
   fee-bot sweep and a spending-limit pull in dry mode, then live on devnet. Verify the pump.fun
   recipient question above on devnet.
2. Code (separate issue, ≤ 400-line PRs): fee-bot sweep + ceiling in `econ/params.json` (timelocked,
   D50); pot accounting reads the vault balance; a spending-limit pull when the hot wallet is short;
   site Docs/FAQ/Risks text updated.
3. Mainnet: kiwi creates the multisig in the Squads app with his signers, sets threshold, time lock and
   the spending limit; posts the vault address in #1; `APPROVED` for the first sweep.

## Trade-offs

- **Signers.** Members are kiwi's keys (e.g. a Phantom on the phone, a hardware wallet, a backup kept
  offline). No Claude session ever holds a signer key (CLAUDE.md rule 1). Losing 2 of 3 keys locks
  the vault for good.
- **Honesty of the message.** Today's site says the dev holds no key to the system wallet. With a
  multisig the dev's signers *can* move the vault, but only through a public proposal that waits 72h.
  The site must say exactly that.
- **Bot changes.** Small (a sweep, a ceiling, one spending-limit pull), but on the money path: tests and a
  devnet run first.
- **Draw.** When the draw is turned on, the prize (one SOL prize, D43) is pulled through the SOL
  spending limit, so the day amount must cover it.

## Options for kiwi

| | What | Protects | Cost |
|---|---|---|---|
| **A (recommended)** | Squads 2-of-3 vault + 72h time lock + daily SOL spending limit for the bot, hourly sweep | The pot and anything above one day of flow | ~0.12 SOL + one code issue |
| **B** | Same sweep, but to a single cold wallet kiwi holds (hardware) | The pot, if kiwi's key is safe | ~0 SOL; no public time lock, "dev holds a key" with no on-chain limit |
| **C** | Keep as is: hardening runbook + honest Risks text | Odds only, not the loss | 0 |

## Sources (official Squads docs, read 2026-11-18)

- Spending limits, app guide: https://docs.squads.so/main/navigating-your-squad/settings/spending-limits
- Spending limits, reference: https://docs.squads.so/main/development/reference/spending-limits
- Add spending limit (SDK, `Period.Day`, members, destinations): https://docs.squads.so/main/development/typescript/instructions/controlled-multisig-instructions/add-spending-limit
- Spending limit periods (ONE_TIME, DAY, WEEK, MONTH): https://developers.squads.so/squads-api/api-reference/v0/endpoint/create-spending-limit
- Create a multisig (0.1 SOL fee, rent): https://docs.squads.so/main/getting-started/create-a-squads-multisig
- Costs of using Squads (spending limit 0.0076, time lock 0.0069 SOL): https://docs.squads.so/main/additional-resources/costs-of-using-squads
- `spending_limit_use` "transfer tokens from a multisig vault to a destination account": program
  source, https://github.com/Squads-Protocol/v4 (`programs/squads_multisig_program/src/lib.rs`)
- v4 audits (Neodyme, OtterSec, Trail of Bits): https://squads.so/blog/spending-limits · Our side: `ops/fee-bot/run.mjs` (`collectCoinCreatorFeeInstructions` signed by the wallet itself),
  `ops/fee-bot/README.md` (recipient set once, then locked), DECISIONS D45, D46, D50.

To verify on devnet before any decision: whether a spending-limit member must also be a multisig member
(then the bot key joins with no vote permission), and the pump.fun recipient question above.
