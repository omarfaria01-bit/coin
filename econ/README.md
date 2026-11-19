# Public economic rules (D50, #345)

`params.json` is the only source of the fee split (70% basket / 30% pot / 0% burn / 0% team, D50; D49 reverted), the fee-bot
caps, slippage and reserves, and the payout-bot caps. The bots load it from the repo checkout.

- **Append, never edit.** A change is a new entry in `versions` with a later `effective_from`.
- **72h timelock.** A version applies only after its `effective_from` and at least 72 hours after the server
  first saw it. Until then the bots keep the previous version. An edited version counts as new.
- **Check it.** `fee-bot.json` and `payouts.json` publish `econ.sha256`: the sha256 of the version in force as
  canonical JSON (sorted keys, no spaces). `node -e 'import("./econ/params.mjs").then(m=>console.log(m.versionHash(JSON.parse(require("fs").readFileSync("econ/params.json")).versions.at(-1))))'`
- Every change is announced in #1 and on the site before it applies.
