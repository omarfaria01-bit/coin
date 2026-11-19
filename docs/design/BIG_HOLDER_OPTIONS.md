# Big holders and rewards — options for kiwi (#342 C, #348)

Status: **note only. No rewards code changes until kiwi chooses.** Owner: S5.

## The problem

Daily rewards are split pro-rata to **balance-hours × loyalty multiplier** (D46, D47;
`engine/rewards.allocate_by_weights`). There is no cap on rewards. The 5%-of-supply cap only applies to
the draw (D39). So a whale's share of rewards is his share of the *eligible* supply: in the example
below, 20% of supply is 36% of every day's rewards. The external review (#342) asks what that means for
a small holder.

## The three options

| | Weight of a wallet | In one line |
|---|---|---|
| **(a) keep pro-rata** | `balance` | Today's rule. Simple, and splitting wallets changes nothing. |
| **(b) cap at 5% of supply** | `min(balance, 5% of supply)` | Same cap as the draw (D39). The part above 5% earns nothing. |
| **(c) sqrt-dampened** | `√balance` | Big wallets count less per token. 100× the balance gives 10× the weight. |

In all three, the loyalty multiplier (D43) and balance-hours (D47) stay as they are: the weight above
replaces only the balance inside `balance × multiplier`, hour by hour.

## Worked example

Assumptions (`sim/big_holder_options.py`, exact Fractions, no floats):

- Market cap €1M, supply 1B tokens, so €1 = 1,000 tokens and €100 = 0.01% of supply.
- **One whale with 20%** of supply.
- **1,000 small holders**: 600 × €100, 300 × €500, 100 × €1,500 (together 36% of supply).
- The other 44% sits in excluded wallets (pool, curve, team, system wallet) and earns nothing.
- Everyone has the same multiplier, so it cancels out. Shares are shown **per €1,000 of daily rewards**:
  multiply by the real budget. The real budget depends on volume; see S1's scenarios report (#342 A).

### Whale in one wallet

| Option | Whale share | €100 holder share | €100 holder per €1,000 | vs (a) | €1,500 holder per €1,000 |
|---|---|---|---|---|---|
| (a) pro-rata | 35.71% | 0.0178% | €0.17 | ×1.00 | €2.67 |
| (b) cap 5% of supply | 12.19% | 0.0243% | €0.24 | ×1.36 | €3.65 |
| (c) sqrt | 2.62% | 0.0587% | €0.58 | ×3.28 | €2.27 |

Reading it:

- **(b)** takes rewards from the whale only and gives them to everyone else in proportion: every small
  holder gets +36%.
- **(c)** takes from every wallet bigger than average, not only the whale. The €100 holder gets ×3.3,
  but the €1,500 holder **loses** 15% (€2.67 → €2.27). Under (c) a holder earns less per euro the more
  euros he holds, which is a big change in the deal "rewards follow what you hold".

### The whale splits into many wallets (sybil)

Same 20%, spread over *n* wallets that cannot be linked (e.g. funded from an exchange). Cells:
whale share / €100 holder per €1,000.

| Whale wallets | (a) pro-rata | (b) cap 5% of supply | (c) sqrt |
|---|---|---|---|
| 1 | 35.71% / €0.17 | 12.19% / €0.24 | 2.62% / €0.58 |
| 4 | 35.71% / €0.17 | 35.71% / €0.17 | 5.12% / €0.57 |
| 10 | 35.71% / €0.17 | 35.71% / €0.17 | 7.86% / €0.55 |
| 100 | 35.71% / €0.17 | 35.71% / €0.17 | 21.24% / €0.47 |

**Splitting weakens (b) and (c).** Under (b) four wallets of 5% undo the cap completely. Under (c),
*n* wallets multiply the whale's weight by √n: with 100 wallets the whale is back to 21% of the
rewards. Splitting is cheap: each extra wallet costs one token-account rent (~0.002 SOL) and a few
transaction fees. Our sybil clustering (`engine/sybil_v033.py`, COIN_MATH §7) links wallets only when
there is on-chain evidence (co-signed or funded transactions); exchange-funded wallets usually leave
none. So (b) and (c) mostly bind honest whales, who do not bother to split.

(a) has no such problem: splitting changes nothing, because the weight is linear.

## Other effects

- **Public message.** (a) "you earn in proportion to what you hold" is easy to explain and verify.
  (b) matches the draw rule we already publish. (c) needs a formula on the site and is harder to check
  by hand.
- **Where the cut goes.** Under (b) and (c) nothing is lost: the whale's cut is shared by the others
  (largest-remainder split, conservation unchanged).
- **Code if chosen.** (b) and (c) are a small change to the weight before `allocate_by_weights`, plus a
  DECISIONS entry, a timelocked `econ/params.json` version (D50, 72h) and site text. The engine already
  has a 5% water-filling cap from COIN_MATH §6 that could be reused for (b). Excluded wallets stay
  excluded in every option.

## Recommendation (for kiwi to decide)

**(b) cap at 5% of supply**, as with the draw: it helps every small holder a little (+36% in the
example), never hurts a holder under 5%, is one rule for both draw and rewards, and is simple to
explain. Say on the site that a determined whale can split wallets around it. (c) helps the €100 holder
more, but it cuts mid-size holders too and is undone by splitting just as well.

## Reproduce

```bash
uv run python -m sim.big_holder_options      # prints the tables above
uv run pytest tests/test_big_holder_options.py
```
