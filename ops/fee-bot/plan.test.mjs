import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applyIncoming,
  applySpent,
  basketFromIndex,
  conserved,
  emptyState,
  planBuys,
  quoteAcceptable,
  splitIncoming,
  stateFromJson,
  stateToJson,
} from "./plan.mjs";

const NOW = Date.parse("2026-11-18T19:00:00Z");
const H = 3_600_000;
const idx = (over = {}) => ({
  as_of: "2026-11-18T18:00:00Z",
  dry_run: false,
  members: [
    { mint: "A", weight_bps: 6000 },
    { mint: "B", weight_bps: 3000 },
    { mint: "C", weight_bps: 1000 },
  ],
  ...over,
});
const caps = (over = {}) => ({
  maxPerRun: 10_000_000_000n,
  maxPerSwap: 10_000_000_000n,
  minSwap: 10_000_000n,
  spentToday: 0n,
  maxPerDay: 20_000_000_000n,
  ...over,
});

test("70/30 split floors the pot and keeps the remainder", () => {
  assert.deepEqual(splitIncoming(1_000_000_001n, 3000n), { pot: 300_000_000n, basket: 700_000_001n });
  assert.throws(() => splitIncoming(-1n, 3000n));
  assert.throws(() => splitIncoming(1n, 10_001n));
});

test("conservation through claims and spends", () => {
  let s = emptyState();
  for (const x of [1n, 7n, 999_999_999n, 123_456_789n]) s = applyIncoming(s, x, 3000n);
  assert.ok(conserved(s));
  s = applySpent(s, s.basketLamports / 2n, "2026-11-18");
  assert.ok(conserved(s));
  assert.throws(() => applySpent(s, s.basketLamports + 1n, "2026-11-18"));
});

test("daily counter resets on a new day", () => {
  let s = applyIncoming(emptyState(), 10_000n, 0n);
  s = applySpent(s, 100n, "2026-11-18");
  s = applySpent(s, 100n, "2026-11-18");
  assert.equal(s.spentTodayLamports, 200n);
  s = applySpent(s, 50n, "2026-11-19");
  assert.equal(s.spentTodayLamports, 50n);
});

test("index gate: dry run, stale, empty, bad weights, self mint", () => {
  assert.equal(basketFromIndex(idx(), NOW, 3 * H, null).ok, true);
  assert.equal(basketFromIndex(idx({ dry_run: true }), NOW, 3 * H, null).reason, "index_dry_run");
  assert.equal(basketFromIndex(idx({ as_of: "2026-11-18T10:00:00Z" }), NOW, 3 * H, null).reason, "index_stale");
  assert.equal(basketFromIndex(idx({ members: [] }), NOW, 3 * H, null).reason, "index_empty");
  const bad = idx({ members: [{ mint: "A", weight_bps: 9000 }] });
  assert.equal(basketFromIndex(bad, NOW, 3 * H, null).reason, "weights_not_10000");
  // the coin's own mint is never bought; then weights no longer sum to 10000 -> refuse
  assert.equal(basketFromIndex(idx(), NOW, 3 * H, "A").reason, "weights_not_10000");
  assert.equal(basketFromIndex(null, NOW, 3 * H, null).reason, "no_index");
});

test("buys follow weights, respect caps, carry the rest", () => {
  const { members } = basketFromIndex(idx(), NOW, 3 * H, null);
  const p = planBuys(1_000_000_000n, members, caps());
  assert.deepEqual(
    p.buys.map((b) => [b.mint, b.lamports]),
    [
      ["A", 600_000_000n],
      ["B", 300_000_000n],
      ["C", 100_000_000n],
    ],
  );
  assert.equal(p.spend + p.carry, 1_000_000_000n);

  const capped = planBuys(1_000_000_000n, members, caps({ maxPerRun: 100_000_000n }));
  assert.equal(capped.spend, 100_000_000n); // 60M + 30M + 10M (C exactly at minSwap)
  assert.ok(capped.buys.every((b) => b.lamports >= 10_000_000n));
  assert.equal(capped.spend + capped.carry, 1_000_000_000n);

  const day = planBuys(1_000_000_000n, members, caps({ spentToday: 20_000_000_000n }));
  assert.equal(day.spend, 0n);
  assert.equal(day.carry, 1_000_000_000n);

  const perSwap = planBuys(1_000_000_000n, members, caps({ maxPerSwap: 200_000_000n }));
  assert.ok(perSwap.buys.every((b) => b.lamports <= 200_000_000n));

  const dust = planBuys(20_000_000n, members, caps());
  assert.deepEqual(
    dust.buys.map((b) => b.mint),
    ["A"],
  ); // B 6M and C 2M are below 0.01 SOL and stay for later
});

test("state json round trip rejects unknown and missing keys", () => {
  const s = applyIncoming(emptyState(), 12345n, 3000n);
  assert.deepEqual(stateFromJson(JSON.parse(JSON.stringify(stateToJson(s)))), s);
  assert.throws(() => stateFromJson({ ...stateToJson(s), extra: 1 }));
  const { potLamports, ...missing } = stateToJson(s);
  assert.throws(() => stateFromJson(missing));
});

test("quote gate", () => {
  const ok = { transaction: "AQ==", slippageBps: 300, priceImpact: -0.5 };
  assert.equal(quoteAcceptable(ok, 300, 3), true);
  assert.equal(quoteAcceptable({ ...ok, slippageBps: 301 }, 300, 3), false);
  assert.equal(quoteAcceptable({ ...ok, priceImpact: -3.5 }, 300, 3), false);
  assert.equal(quoteAcceptable({ ...ok, transaction: "" }, 300, 3), false);
  assert.equal(quoteAcceptable(null, 300, 3), false);
});
