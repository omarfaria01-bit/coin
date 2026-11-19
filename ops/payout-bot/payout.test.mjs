import assert from "node:assert/strict";
import { test } from "node:test";

import { HOLDERS, MINT_A, MINT_B, SYS, makePlan } from "./fixtures.mjs";
import { ATA_PROGRAM, MEMO_PROGRAM, SYSTEM_PROGRAM, TOKEN, TOKEN_2022, isPubkey, publicSummary, selectTodo, transferInstructions, validatePlan } from "./payout.mjs";

test("pubkey check and plan validation", () => {
  assert.ok(isPubkey(TOKEN) && isPubkey(SYSTEM_PROGRAM) && isPubkey(SYS));
  assert.ok(!isPubkey("abc") && !isPubkey(`${SYS}0`) && !isPubkey("1".repeat(33)));
  validatePlan(makePlan());
  const bad = (f, re) => {
    const p = makePlan();
    f(p);
    assert.throws(() => validatePlan(p), re);
  };
  bad((p) => (p.extra = 1), /unknown key plan.extra/);
  bad((p) => (p.transfers[0].memo = "GTASP10:pay:x"), /memo/);
  bad((p) => p.transfers.push({ ...p.transfers[0] }), /duplicate memo/);
  bad((p) => (p.transfers[0].amount = "1.5"), /integer string/);
  bad((p) => (p.transfers[0].amount = "0"), />= 1/);
  bad((p) => (p.totals[MINT_A].paid = "949"), /paid \+ carried/);
  bad((p) => (p.totals[MINT_B].carried = "11") && (p.totals[MINT_B].accrued = "101"), /sum of carried/);
  bad((p) => (p.excluded[0].wallet = HOLDERS[0]), /excluded wallet/);
  bad((p) => (p.schema = 2), /schema/);
});

test("instruction layout: create-idempotent ATA, TransferChecked, memo (Token-2022)", () => {
  const ata = (o, m, p) => `ata(${o},${m},${p})`;
  const t = { ...makePlan().transfers[3], programId: TOKEN_2022, decimals: 6 };
  const [create, xfer, memo] = transferInstructions(t, SYS, ata);
  assert.equal(create.programId, ATA_PROGRAM);
  assert.equal(create.keys[5].pubkey, TOKEN_2022);
  assert.equal(xfer.programId, TOKEN_2022);
  assert.deepEqual([...xfer.data], [12, 70, 0, 0, 0, 0, 0, 0, 0, 6]);
  assert.equal(xfer.keys[0].pubkey, ata(SYS, MINT_B, TOKEN_2022));
  assert.equal(memo.programId, MEMO_PROGRAM);
  assert.equal(new TextDecoder().decode(memo.data), t.memo);
  assert.throws(() => transferInstructions({ ...t, programId: SYSTEM_PROGRAM }, SYS, ata), /unknown token program/);
});

test("selectTodo: ledger, on-chain and pending rules; publicSummary keeps only sent", () => {
  const p = makePlan();
  const [a, b, c] = p.transfers;
  const led = [
    { event: "transfer", status: "sent", day: p.day, memo: a.memo, wallet: a.wallet, mint: a.mint, amount: a.amount, sig: "s1" },
    { event: "transfer", status: "pending", day: p.day, memo: b.memo, t: 1000 },
    { event: "transfer", status: "dry", day: p.day, memo: c.memo },
  ];
  const sel = selectTodo(p, led, new Map([[p.transfers[3].memo, "s2"]]), 2000, { maxTransfersPerDay: 1000 });
  assert.deepEqual(sel.todo.map((t) => t.memo), [c.memo, p.transfers[4].memo]);
  assert.deepEqual(sel.done.map((t) => t.sig), ["s2"]);
  assert.deepEqual(sel.skipped, [{ memo: b.memo, reason: "pending" }]);
  const capped = selectTodo(p, led, new Map(), 2000, { maxTransfersPerDay: 2 });
  assert.equal(capped.todo.length, 1);
  const pub = publicSummary(led, SYS, "now");
  assert.deepEqual(pub.days[0].transfers, [{ wallet: a.wallet, mint: a.mint, amount: a.amount, sig: "s1" }]);
});
