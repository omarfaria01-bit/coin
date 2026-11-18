import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { Keypair, SystemProgram, Transaction } from "@solana/web3.js";

import { forwardedLamports, loadConfig, loadKeypair } from "./run.mjs";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "feebot-"));
const example = JSON.parse(fs.readFileSync(new URL("./config.example.json", import.meta.url), "utf8"));
const writeCfg = (over) => {
  const f = path.join(dir, `cfg-${Math.random()}.json`);
  fs.writeFileSync(f, JSON.stringify({ ...example, ...over }));
  return f;
};

const seenFile = path.join(dir, "econ_seen.json");
const load = (over) => loadConfig(writeCfg(over), { seenFile });

test("example config loads; split, caps and slippage come from econ/params.json", () => {
  const cfg = load({});
  assert.equal(cfg.mode, "dry");
  assert.equal(cfg.pot_bps, 2800);
  assert.equal(cfg.burn_bps, 500);
  assert.equal(cfg.slippage_bps, 300);
  assert.match(cfg.econ.sha256, /^[0-9a-f]{64}$/);
});

test("config rejects unknown keys, bad mode or mint, and any local change of a public rule", () => {
  assert.throws(() => load({ extra: 1 }), /unknown config key/);
  assert.throws(() => load({ mode: "yolo" }), /mode/);
  assert.throws(() => load({ mint: "not-a-mint" }));
  assert.throws(() => load({ pot_bps: 3000 }), /public rule/);
  assert.throws(() => load({ slippage_bps: 100 }), /public rule/);
  assert.throws(() => load({ max_per_run_lamports: "9000000000" }), /public rule/);
  const smoke = load({ max_per_run_lamports: "20000000" }); // lowering a cap is allowed and public
  assert.equal(smoke.max_per_run_lamports, "20000000");
  assert.deepEqual(smoke.econ.local_lower_caps, { max_per_run_lamports: "20000000" });
  assert.equal(load({ mode: "live" }).burn_bps, 500); // live runs; the burn share is held until #344
});

test("keypair must be a private file; loaded key matches", () => {
  const kp = Keypair.generate();
  const f = path.join(dir, "kp.json");
  fs.writeFileSync(f, JSON.stringify(Array.from(kp.secretKey)), { mode: 0o644 });
  fs.chmodSync(f, 0o644);
  assert.throws(() => loadKeypair(f), /chmod 600/);
  fs.chmodSync(f, 0o600);
  assert.equal(loadKeypair(f).publicKey.toBase58(), kp.publicKey.toBase58());
  fs.writeFileSync(f, JSON.stringify([1, 2, 3]));
  assert.throws(() => loadKeypair(f), /64-byte/);
});

test("source never logs or serializes the secret key", () => {
  for (const name of ["run.mjs", "keygen.mjs", "plan.mjs"]) {
    const src = fs.readFileSync(new URL(`./${name}`, import.meta.url), "utf8");
    for (const line of src.split("\n")) {
      if (/console\.|log\(/.test(line)) {
        assert.doesNotMatch(line, /secretKey|keyFile|HELIUS_API_KEY|api-key=\$\{|\bkey\b\)/, `${name}: ${line}`);
      }
    }
  }
});

test("fee_mode forwarded: needs forward_from; counts only transfers from it to the system wallet", () => {
  const from = "E8JgzMnBJU5Mwbsmw88SyivaDiUYJNjkupU53UEG4uXJ";
  const me = "3annmAegHQt6ru4Qd9w9fyK1FDseY7u4iyXfeeR3hJkd";
  assert.equal(load({ fee_mode: "forwarded", forward_from: from }).forward_from, from);
  assert.throws(() => load({ fee_mode: "forwarded" }), /forward_from/);
  assert.throws(() => load({ forward_from: from }), /forward_from/);
  const xfer = (source, destination, lamports) => ({ program: "system", parsed: { type: "transfer", info: { source, destination, lamports } } });
  const txs = [
    { sig: "a", tx: { meta: { err: null }, transaction: { message: { instructions: [xfer(from, me, 1_000)] } } } },
    { sig: "b", tx: { meta: { err: null }, transaction: { message: { instructions: [xfer("Other111", me, 5_000)] } } } },
    { sig: "c", tx: { meta: { err: { x: 1 } }, transaction: { message: { instructions: [xfer(from, me, 7_000)] } } } },
    { sig: "d", tx: { meta: { err: null }, transaction: { message: { instructions: [xfer(me, from, 9_000), xfer(from, me, 250)] } } } },
    { sig: "e", tx: null },
  ];
  assert.deepEqual(forwardedLamports(txs, from, me), { total: 1_250n, sigs: ["a", "d"] });
});


test("loadKeypair returns a key that still signs (regression: zeroing wiped the secret)", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kp-"));
  const file = path.join(dir, "k.json");
  const orig = Keypair.generate();
  fs.writeFileSync(file, JSON.stringify(Array.from(orig.secretKey)), { mode: 0o600 });
  const kp = loadKeypair(file);
  assert.equal(kp.publicKey.toBase58(), orig.publicKey.toBase58());
  const tx = new Transaction({ feePayer: kp.publicKey, recentBlockhash: orig.publicKey.toBase58() });
  tx.add(SystemProgram.transfer({ fromPubkey: kp.publicKey, toPubkey: orig.publicKey, lamports: 1 }));
  tx.sign(kp);
  assert.equal(tx.verifySignatures(), true);
});
