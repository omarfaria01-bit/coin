import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { MINT_A, MINT_B, SYS, makePlan } from "./fixtures.mjs";
import { TOKEN, TOKEN_2022 } from "./payout.mjs";
import { loadConfig, main, readSecret, run } from "./send.mjs";

/** Mock chain: records sends; memos it sent count as on-chain afterwards. */
function mockChain(over = {}) {
  const c = {
    wallet: SYS, sent: [], simulated: 0, chainMemos: new Map(), sol: 1_000_000_000n,
    tokens: { [MINT_A]: 10_000n, [MINT_B]: 10_000n },
    mintInfo: async (m) => ({ programId: m === MINT_B ? TOKEN_2022 : TOKEN, decimals: 6 }),
    tokenBalance: async (m) => c.tokens[m] ?? 0n,
    solBalance: async () => c.sol,
    missingAtas: async (items) => items.length,
    confirmedMemos: async () => new Map(c.chainMemos),
    simulate: async () => (c.simulated++, { err: null }),
    send: async (items) => {
      const sig = `sig${c.sent.length}`;
      c.sent.push(items);
      for (const t of items) c.chainMemos.set(t.memo, sig);
      return sig;
    },
    ...over,
  };
  return c;
}

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "payout-"));
function cfgFor(dir, over = {}) {
  return {
    enabled: true, mode: "live", max_transfers_per_day: 1000, max_transfers_per_tx: 3, min_reserve_lamports: "50000000",
    fee_bot_state_path: path.join(dir, "fee-state.json"), state_dir: dir, public_path: path.join(dir, "payouts.json"), ...over,
  };
}
const quiet = () => {};
const sentCount = (c) => c.sent.flat().length;
const ledger = (dir) => fs.readFileSync(path.join(dir, "ledger.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));

test("dry mode simulates and sends nothing; a later live run still pays everything", async () => {
  const dir = tmp();
  const chain = mockChain({ send: async () => assert.fail("dry mode must not send") });
  assert.equal(await run({ cfg: cfgFor(dir, { mode: "dry" }), plan: makePlan(), chain, log: quiet }), 0);
  assert.equal(chain.simulated, 2); // 5 transfers, 3 per tx
  assert.ok(ledger(dir).every((e) => e.status === "dry"));
  assert.ok(!fs.existsSync(path.join(dir, "payouts.json")));
  const live = mockChain();
  assert.equal(await run({ cfg: cfgFor(dir), plan: makePlan(), chain: live, log: quiet }), 0);
  assert.equal(sentCount(live), 5);
});

test("re-running the same plan pays nothing twice (ledger and on-chain checks)", async () => {
  const dir = tmp();
  const chain = mockChain();
  await run({ cfg: cfgFor(dir), plan: makePlan(), chain, log: quiet });
  await run({ cfg: cfgFor(dir), plan: makePlan(), chain, log: quiet });
  assert.equal(sentCount(chain), 5);
  // Ledger lost: the on-chain memos alone still stop a second payment.
  const dir2 = tmp();
  await run({ cfg: cfgFor(dir2), plan: makePlan(), chain, log: quiet });
  assert.equal(sentCount(chain), 5);
  const pub = JSON.parse(fs.readFileSync(path.join(dir2, "payouts.json"), "utf8"));
  assert.equal(pub.days[0].transfers.length, 5);
  assert.deepEqual(pub.days[0].carried_total, { [MINT_A]: "0", [MINT_B]: "10" });
  // Conservation per mint: public transfers == plan totals.paid.
  for (const m of [MINT_A, MINT_B]) {
    const sum = pub.days[0].transfers.filter((t) => t.mint === m).reduce((a, t) => a + BigInt(t.amount), 0n);
    assert.equal(String(sum), makePlan().totals[m].paid);
  }
});

test("a pending send is not retried until its blockhash is dead, and not at all if it landed", async () => {
  const dir = tmp();
  let t = 1_000_000;
  const chain = mockChain({ send: async () => { throw new Error("rpc timeout"); } });
  assert.equal(await run({ cfg: cfgFor(dir), plan: makePlan(), chain, now: () => t, log: quiet }), 4);
  const ok = mockChain();
  t += 60_000;
  await run({ cfg: cfgFor(dir), plan: makePlan(), chain: ok, now: () => t, log: quiet });
  assert.equal(sentCount(ok), 2); // first batch of 3 still pending; the other 2 go
  ok.chainMemos.set(makePlan().transfers[0].memo, "landed-late");
  t += 10 * 60_000;
  await run({ cfg: cfgFor(dir), plan: makePlan(), chain: ok, now: () => t, log: quiet });
  assert.equal(sentCount(ok), 4); // transfers[1], [2] resent; [0] had landed
});

test("the per-day cap stops the run and holds on re-run", async () => {
  const dir = tmp();
  const chain = mockChain();
  assert.equal(await run({ cfg: cfgFor(dir, { max_transfers_per_day: 2 }), plan: makePlan(), chain, log: quiet }), 3);
  assert.equal(await run({ cfg: cfgFor(dir, { max_transfers_per_day: 2 }), plan: makePlan(), chain, log: quiet }), 3);
  assert.equal(sentCount(chain), 2);
});

test("never sends more than held; keeps the fee bot's SOL and the reserve", async () => {
  const dir = tmp();
  const chain = mockChain();
  chain.tokens[MINT_B] = 89n; // plan pays 90
  assert.equal(await run({ cfg: cfgFor(dir), plan: makePlan(), chain, log: quiet }), 2);
  assert.ok(chain.sent.flat().every((t) => t.mint === MINT_A));
  const dir2 = tmp();
  fs.writeFileSync(path.join(dir2, "fee-state.json"), JSON.stringify({ potLamports: "940000000", basketLamports: "0" }));
  const poor = mockChain(); // 1 SOL - 0.94 owed - 0.05 reserve < 5 ATAs + 2 fees
  assert.equal(await run({ cfg: cfgFor(dir2), plan: makePlan(), chain: poor, log: quiet }), 2);
  assert.equal(sentCount(poor), 0);
});

test("STOP file and enabled=false stop before reading the plan or the key", async () => {
  const dir = tmp();
  const cfgFile = path.join(dir, "config.json");
  const example = JSON.parse(fs.readFileSync(new URL("./config.example.json", import.meta.url), "utf8"));
  fs.writeFileSync(cfgFile, JSON.stringify({ ...example, enabled: false }));
  assert.equal(await main(["--config", cfgFile, "--plan", "/nonexistent.json"]), 0);
  fs.writeFileSync(cfgFile, JSON.stringify(example));
  fs.writeFileSync(path.join(dir, "STOP"), "");
  assert.equal(await main(["--config", cfgFile, "--plan", "/nonexistent.json"]), 0);
  assert.equal(loadConfig(cfgFile).mode, "dry");
  fs.writeFileSync(cfgFile, JSON.stringify({ ...example, extra: 1 }));
  assert.throws(() => loadConfig(cfgFile), /unknown config key/);
});

test("Token-2022 mint takes the Token-2022 program", async () => {
  const chain = mockChain();
  await run({ cfg: cfgFor(tmp()), plan: makePlan(), chain, log: quiet });
  for (const t of chain.sent.flat()) assert.equal(t.programId, t.mint === MINT_B ? TOKEN_2022 : TOKEN);
});

test("a too-large batch is split, nothing lost or doubled", async () => {
  const chain = mockChain();
  const send = chain.send;
  chain.send = async (items) => {
    if (items.length > 1) throw Object.assign(new Error("too big"), { tooLarge: true });
    return send(items);
  };
  assert.equal(await run({ cfg: cfgFor(tmp()), plan: makePlan(), chain, log: quiet }), 0);
  assert.equal(new Set(chain.sent.flat().map((t) => t.memo)).size, 5);
  assert.equal(sentCount(chain), 5);
});

test("keypair rules; source never logs the key or env values", () => {
  const f = path.join(tmp(), "kp.json");
  fs.writeFileSync(f, JSON.stringify([...crypto.randomBytes(64)]), { mode: 0o644 });
  fs.chmodSync(f, 0o644);
  assert.throws(() => readSecret(f), /chmod 600/);
  fs.chmodSync(f, 0o600);
  assert.equal(readSecret(f).length, 64);
  for (const name of ["send.mjs", "payout.mjs"]) {
    for (const line of fs.readFileSync(new URL(`./${name}`, import.meta.url), "utf8").split("\n")) {
      if (/console\.|log\(/.test(line)) assert.doesNotMatch(line, /secret|heliusKey|HELIUS_API_KEY|rpcUrl|api-key=\$\{/, `${name}: ${line}`);
    }
  }
});
