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
