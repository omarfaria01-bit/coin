// Pure planning for the GTASP10 fee bot (D45). No I/O, no clock, no keys.
// Amounts are BigInt lamports. Every split returns its remainder; nothing is lost.

const BPS = 10_000n;

/**
 * Split newly received creator fees: pot = floor(in * potBps / 10000), burn = floor(in * burnBps / 10000),
 * basket = the rest. The burn share (D49) is held in `burnLamports` until buyback & burn runs (#344).
 */
export function splitIncoming(lamports, potBps, burnBps = 0n) {
  if (lamports < 0n) throw new Error("negative incoming");
  if (potBps < 0n || burnBps < 0n || potBps + burnBps > BPS) throw new Error("bps out of range");
  const pot = (lamports * potBps) / BPS;
  const burn = (lamports * burnBps) / BPS;
  return { pot, burn, basket: lamports - pot - burn };
}

/** Apply one claim to the state. Pure: returns a new state. */
export function applyIncoming(state, lamports, potBps, burnBps = 0n) {
  const { pot, burn, basket } = splitIncoming(lamports, potBps, burnBps);
  return {
    ...state,
    potLamports: state.potLamports + pot,
    burnLamports: state.burnLamports + burn,
    basketLamports: state.basketLamports + basket,
    totalInLamports: state.totalInLamports + lamports,
  };
}

/**
 * Members usable for buying: published (not dry-run), fresh, weights summing to 10000.
 * Returns { ok, reason, members:[{mint, weightBps}] }.
 */
export function basketFromIndex(indexOut, nowMs, maxAgeMs, selfMint) {
  if (!indexOut || !Array.isArray(indexOut.members)) return { ok: false, reason: "no_index" };
  if (indexOut.dry_run) return { ok: false, reason: "index_dry_run" };
  const asOf = Date.parse(indexOut.as_of);
  if (!Number.isFinite(asOf)) return { ok: false, reason: "index_no_as_of" };
  if (nowMs - asOf > maxAgeMs) return { ok: false, reason: "index_stale" };
  const members = indexOut.members
    .map((m) => ({ mint: String(m.mint), weightBps: BigInt(m.weight_bps) }))
    .filter((m) => m.mint !== selfMint && m.weightBps > 0n);
  if (members.length === 0) return { ok: false, reason: "index_empty" };
  const sum = members.reduce((a, m) => a + m.weightBps, 0n);
  if (sum !== BPS) return { ok: false, reason: "weights_not_10000" };
  return { ok: true, reason: "ok", members };
}

/**
 * Plan basket buys. Spend at most min(basket, caps), keep reserve out of it.
 * Each member gets floor(spend * w / 10000); parts below minSwap are not bought.
 * Returns { buys:[{mint, lamports}], spend, carry } with spend + carry == budget.
 */
export function planBuys(basketLamports, members, caps) {
  const { maxPerRun, maxPerSwap, minSwap, spentToday, maxPerDay } = caps;
  const dayLeft = maxPerDay > spentToday ? maxPerDay - spentToday : 0n;
  let budget = basketLamports;
  if (budget > maxPerRun) budget = maxPerRun;
  if (budget > dayLeft) budget = dayLeft;
  const buys = [];
  let spend = 0n;
  for (const m of members) {
    let part = (budget * m.weightBps) / BPS;
    if (part > maxPerSwap) part = maxPerSwap;
    if (part < minSwap) continue;
    buys.push({ mint: m.mint, lamports: part });
    spend += part;
  }
  return { buys, spend, carry: basketLamports - spend };
}

/** After swaps: subtract only what actually left the wallet for each buy. */
export function applySpent(state, spentLamports, dayKey) {
  if (spentLamports < 0n || spentLamports > state.basketLamports) throw new Error("bad spend");
  const sameDay = state.dayKey === dayKey;
  return {
    ...state,
    basketLamports: state.basketLamports - spentLamports,
    totalSpentLamports: state.totalSpentLamports + spentLamports,
    dayKey,
    spentTodayLamports: (sameDay ? state.spentTodayLamports : 0n) + spentLamports,
  };
}

/**
 * D46 payout rent: SOL to move from the basket budget into free SOL before buying, so the payout
 * sender can open token accounts for new holders. free = wallet - pot - basket - reserve.
 * Tops free SOL up to `target`, never more than the basket holds or the day's cap allows.
 */
export function rentTopUp(basketLamports, freeLamports, targetLamports, dayLeftLamports) {
  let x = targetLamports > freeLamports ? targetLamports - freeLamports : 0n;
  if (x > basketLamports) x = basketLamports;
  if (x > dayLeftLamports) x = dayLeftLamports;
  return x > 0n ? x : 0n;
}

/** Conservation: everything that came in is either still in pot/burn/basket or was spent. */
export function conserved(state) {
  return state.totalInLamports === state.potLamports + state.burnLamports + state.basketLamports + state.totalSpentLamports;
}

/** SOL the wallet holds for others (pot, burn share, basket budget): never spent on anything else. */
export function owedLamports(state) {
  return state.potLamports + state.burnLamports + state.basketLamports;
}

export function emptyState() {
  return {
    potLamports: 0n,
    burnLamports: 0n,
    basketLamports: 0n,
    totalInLamports: 0n,
    totalSpentLamports: 0n,
    dayKey: "",
    spentTodayLamports: 0n,
  };
}

export function stateToJson(s) {
  return Object.fromEntries(Object.entries(s).map(([k, v]) => [k, typeof v === "bigint" ? v.toString() : v]));
}

export function stateFromJson(o) {
  const base = emptyState();
  for (const k of Object.keys(base)) {
    if (k === "burnLamports" && !(k in o)) continue; // state from before D49: nothing held for burn yet
    if (!(k in o)) throw new Error(`state missing ${k}`);
    base[k] = typeof base[k] === "bigint" ? BigInt(o[k]) : String(o[k]);
  }
  for (const k of Object.keys(o)) if (!(k in base)) throw new Error(`unknown state key ${k}`);
  return base;
}

/** Slippage gate on a Jupiter quote: refuse if the quote's own slippage or impact is too high. */
export function quoteAcceptable(order, maxSlippageBps, maxImpactPct) {
  if (!order || typeof order.transaction !== "string" || order.transaction === "") return false;
  if (Number(order.slippageBps) > maxSlippageBps) return false;
  const impact = Math.abs(Number(order.priceImpact ?? 0));
  return Number.isFinite(impact) && impact <= maxImpactPct;
}
