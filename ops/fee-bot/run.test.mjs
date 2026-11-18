import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { Keypair } from "@solana/web3.js";

import { loadConfig, loadKeypair } from "./run.mjs";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "feebot-"));
const example = JSON.parse(fs.readFileSync(new URL("./config.example.json", import.meta.url), "utf8"));
const writeCfg = (over) => {
  const f = path.join(dir, `cfg-${Math.random()}.json`);
  fs.writeFileSync(f, JSON.stringify({ ...example, ...over }));
  return f;
};

test("example config loads", () => {
  assert.equal(loadConfig(writeCfg({})).mode, "dry");
});

test("config rejects unknown keys, wrong types, high slippage, other splits, bad mint", () => {
  assert.throws(() => loadConfig(writeCfg({ extra: 1 })), /unknown config key/);
  assert.throws(() => loadConfig(writeCfg({ max_per_run_lamports: 5 })), /must be string/);
  assert.throws(() => loadConfig(writeCfg({ slippage_bps: 301 })), /slippage/);
  assert.throws(() => loadConfig(writeCfg({ pot_bps: 2000 })), /pot_bps/);
  assert.throws(() => loadConfig(writeCfg({ mode: "yolo" })), /mode/);
  assert.throws(() => loadConfig(writeCfg({ mint: "not-a-mint" })));
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
