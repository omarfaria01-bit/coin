# @GTASP10 X profile copy

> **DRAFT — needs kiwi APPROVED before anything is published.**
> Nothing in this file has been posted anywhere. Issue #156. Draw wording is legally gated (#8).

Character counts are plain characters (newlines count as 1). X counts every link as 23 characters,
so posts with a link show both numbers. Limits: bio 160, display name 50, post 280 (new account, no long posts).

Sources checked: COIN_MATH.md §9 (draws, as updated by D39), INDEX_RULES.md §3/§5/§6/§7,
coord/DECISIONS.md D26, D28, D35–D39. No numbers outside those files.

## 1. Bio (151 / 160)

```
GTA 6 memecoin index on Solana. Top 10 GTA coins, rebalanced hourly by a public formula. 0% of fees to the team. 100% to holders. Not financial advice.
```

Website field: `https://desk.linkgox.com/gtasp10/`

## 2. Display name options (max 50)

X rejected plain `GTASP10`. Try in this order:

| # | Name | Chars |
|---|---|---|
| 1 | `GTASP10 Index` | 13 |
| 2 | `GTASP10 \| GTA 6 Index` | 21 |
| 3 | `GTA 6 Memecoin Index` | 20 |

(Option 2 is `GTASP10 | GTA 6 Index`; the backslash is only markdown table escaping.)

## 3. Pinned thread (6 posts, each ≤ 280)

**1/6** (241 chars; 231 as X counts the link)
```
GTASP10 is a GTA 6 memecoin index on Solana.

It tracks the top 10 GTA memecoins and rebalances every hour by a public formula. Anyone can recompute it from the published inputs.

Launch: 19 Nov 2026.
https://desk.linkgox.com/gtasp10/

(1/6)
```

**2/6** (259 chars)
```
How a coin gets in. Every hour, each candidate must pass all filters, including:
- $50k+ liquidity
- at least 4h old
- real trading fees and real traders
- top 10 holders at most 30% of supply
- mint and freeze authority revoked

Fail one and it's out.

(2/6)
```

**3/6** (229 chars)
```
Weights: 50% market cap + 50% volume, capped at 25% per coin.

A new coin must reach the top 8 to enter. A member leaves when it falls below 12th or fails a filter.

Same public rules every hour. Every result is published.

(3/6)
```

**4/6** (218 chars)
```
Fees: 0% of fees to the team. 100% to holders.

Creator fees are split 70% holder rewards, 30% draw pot. Both are paid in the index basket (the top 10 coins). Nothing is promised: amounts depend on real trading.

(4/6)
```

**5/6** (246 chars) — draw wording needs kiwi's approval (legal #8)
```
Planned at launch: an hourly holder draw.
- odds in proportion to your holdings
- max 5% of supply counts per holder
- 0.01% of supply minimum to enter
- inputs sealed before the draw, randomness from ORAO on-chain VRF, checkable by anyone

(5/6)
```

**6/6** (240 chars; 230 as X counts the link)
```
Stay safe:
- We never DM first.
- We never ask for your seed phrase or private key.
- There is no "connect wallet to claim".
Anyone who does is not us.

Not financial advice. Memecoins are high risk.
https://desk.linkgox.com/gtasp10/

(6/6)
```

## Wording rules this copy follows

- No APR, yield, "guaranteed" or profit promises.
- No "no buyback", no "no team share", no "zero team tokens". Fee line is exactly:
  "0% of fees to the team. 100% to holders."
- The draw is described as "planned at launch", not as live.

## Notes for kiwi

1. **~2% della supply del team: CONFERMATO da kiwi (18 Nov 14:45 Rome), va dichiarato.** Il sito lo dichiara già. Per X serve il tuo APPROVED sul testo esatto. Opzioni:
   - Bio (153 / 160), sostituisce la bio sopra:
     `GTA 6 memecoin index on Solana. Top 10 GTA coins, rebalanced hourly by a public formula. 0% of fees to the team. 100% to holders. Founder holds ~2%. NFA.`
   - Post 4/6, aggiungere prima di `(4/6)` (totale 264 / 280):
     `Disclosure: the founder holds ~2% of supply.`
   - Variante con wallet pubblico (meglio, se vuoi): `Disclosure: the founder holds ~2% of supply, in a public wallet: <address>.`
     (controllare la lunghezza una volta noto l'indirizzo).
   Finché non confermi, non pubblichiamo nessuna frase sulle quote del team.
2. **Draw: serve il tuo OK (problema legale #8).** Le draw sono ancora OFF (D28/D39) finché il gate legale
   (COIN_MATH §16) e il test VRF su devnet non sono chiusi. Il post 5/6 dice "Planned at launch". Se il gate non
   è chiuso al lancio, opzioni: (a) togliere il post 5/6 e fare un thread da 5; (b) cambiare la prima riga in
   "Planned, pending legal review: an hourly holder draw."
3. **Precisione "odds in proportion to your holdings".** Tecnicamente le probabilità sono proporzionali allo
   score (saldo, max 5% supply, moltiplicato per il moltiplicatore di tempo di possesso, minimo 1h, D27/D39).
   Versione più precisa se preferisci: `- odds in proportion to your score (holdings x hold time)`.
   Inoltre: con meno di 100 gruppi idonei non c'è draw e il pot passa all'ora dopo (D39).
4. **Launch 19 Nov 2026.** Il sito mostra il countdown a "Nov 19, 12:00 AM ET". Se il token esce a un'altra ora,
   aggiungerla al post 1/6.
5. **Il sito è indietro sui filtri.** `web/index.html` mostra ancora "Top 10 holders 13–27%", "Creator ≤ 3 tokens
   in 7 days" e "200+ traders"; dopo D38 sono "≤ 30%", F7 rimosso e 50 trader. Il thread usa le regole attuali.
   Da sistemare sul sito prima di pubblicare, così thread e sito dicono la stessa cosa.
6. Niente viene pubblicato senza il tuo `APPROVED` sul testo esatto.
