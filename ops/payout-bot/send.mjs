#!/usr/bin/env node
// GTASP10 payout sender (D46): executes payout-plan.json from the system wallet. The memo per
// (day, wallet, mint) is the idempotency key, checked in the ledger and on chain before sending.
// Guards: key file 0600 and never printed; STOP / enabled=false; dry = simulate only; per-day cap;
// never more of a mint than held; keeps the fee bot's pot + basket + reserve SOL (D45); lock.
// Usage: node send.mjs --plan /var/lib/coin/payout-bot/plan-<day>.json [--config /etc/coin/payout-bot/config.json]

import fs from "node:fs";
import path from "node:path";

import { batches, fitBalances, publicSummary, selectTodo, solNeeded, transferInstructions, validatePlan } from "./payout.mjs";

const CONFIG_KEYS = {
  enabled: "boolean",
  mode: "string", // "dry" | "live"
  max_transfers_per_day: "number",
  max_transfers_per_tx: "number",
  min_reserve_lamports: "string",
  fee_bot_state_path: "string",
  state_dir: "string",
  public_path: "string",
};

const defaultLog = (event, data = {}) => console.log(JSON.stringify({ t: new Date().toISOString(), event, ...data }));

export function loadConfig(file) {
  const cfg = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const k of Object.keys(cfg)) if (!(k in CONFIG_KEYS)) throw new Error(`unknown config key ${k}`);
  for (const [k, t] of Object.entries(CONFIG_KEYS)) if (typeof cfg[k] !== t) throw new Error(`config ${k} must be ${t}`);
  if (!["dry", "live"].includes(cfg.mode)) throw new Error("mode must be dry or live");
  if (!(cfg.max_transfers_per_tx >= 1 && cfg.max_transfers_per_tx <= 4)) throw new Error("max_transfers_per_tx must be 1..4");
  if (!(cfg.max_transfers_per_day >= 0)) throw new Error("max_transfers_per_day must be >= 0");
  BigInt(cfg.min_reserve_lamports);
  return cfg;
}

/** Secret key bytes from a private file owned by this user. Never logged. */
export function readSecret(file) {
  const st = fs.statSync(file);
  if ((st.mode & 0o077) !== 0) throw new Error("keypair file must be chmod 600");
  if (typeof process.getuid === "function" && st.uid !== process.getuid()) throw new Error("keypair file must be owned by the bot user");
  const raw = Uint8Array.from(JSON.parse(fs.readFileSync(file, "utf8")));
  if (raw.length !== 64) throw new Error("keypair file is not a 64-byte secret key");
  return raw;
}

const readLedger = (dir) => {
  const f = path.join(dir, "ledger.jsonl");
  if (!fs.existsSync(f)) return [];
  return fs.readFileSync(f, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
};

function writeAtomic(file, text) {
  fs.writeFileSync(`${file}.tmp`, text, { mode: 0o644 });
  fs.renameSync(`${file}.tmp`, file);
}

/** SOL the fee bot still owes (pot + basket budget, D45); must not be spent on payouts. */
function feeBotOwed(file) {
  if (!file || !fs.existsSync(file)) return 0n;
  const s = JSON.parse(fs.readFileSync(file, "utf8"));
  return BigInt(s.potLamports ?? 0) + BigInt(s.basketLamports ?? 0);
}

/**
 * One run over a validated plan. `chain` is the only way to the network (mocked in tests).
 * Returns an exit code: 0 ok, 2 refused (balance/reserve), 3 day cap reached, 4 a send failed.
 */
export async function run({ cfg, plan, chain, now = Date.now, log = defaultLog }) {
  const dir = cfg.state_dir;
  const append = (e) => fs.appendFileSync(path.join(dir, "ledger.jsonl"), `${JSON.stringify({ t: now(), ...e })}\n`);
  if (plan.system_wallet !== chain.wallet) throw new Error("plan.system_wallet is not this bot's wallet");
  const live = cfg.mode === "live";
  const ledger = readLedger(dir);
  if (live && !ledger.some((e) => e.event === "plan" && e.day === plan.day)) {
    const carried_total = Object.fromEntries(Object.entries(plan.totals).map(([m, t]) => [m, t.carried]));
    append({ event: "plan", day: plan.day, carried_total, excluded: plan.excluded });
  }

  const onChain = await chain.confirmedMemos();
  const sel = selectTodo(plan, ledger, onChain, now(), { maxTransfersPerDay: cfg.max_transfers_per_day });
  for (const d of sel.done) if (live) append({ event: "transfer", status: "sent", day: plan.day, ...d, found: "chain" });
  for (const s of sel.skipped) log("skipped", s);

  const info = new Map();
  const balances = new Map();
  for (const m of new Set(sel.todo.map((t) => t.mint))) {
    info.set(m, await chain.mintInfo(m));
    balances.set(m, await chain.tokenBalance(m, info.get(m).programId));
  }
  const fit = fitBalances(sel.todo, balances);
  for (const m of fit.short) log("insufficient_tokens", { mint: m, have: String(balances.get(m) ?? 0n) });
  const items = fit.ok.map((t) => ({ ...t, ...info.get(t.mint) }));

  const sol = await chain.solBalance();
  const keep = feeBotOwed(cfg.fee_bot_state_path) + BigInt(cfg.min_reserve_lamports);
  const need = solNeeded(items, await chain.missingAtas(items), cfg.max_transfers_per_tx);
  log("plan", { day: plan.day, mode: cfg.mode, todo: items.length, skipped: sel.skipped.length, sol: String(sol), keep: String(keep), need: String(need) });
  if (items.length && sol < keep + need) {
    log("low_reserve", { sol: String(sol), keep: String(keep), need: String(need) });
    return 2;
  }

  const sendBatch = async (batch) => {
    if (!live) {
      const sim = await chain.simulate(batch);
      for (const t of batch) append({ event: "transfer", status: "dry", day: plan.day, memo: t.memo, wallet: t.wallet, mint: t.mint, amount: t.amount, sim_err: sim.err ?? null });
      log("dry_batch", { n: batch.length, err: sim.err ?? null });
      return true;
    }
    for (const t of batch) append({ event: "transfer", status: "pending", day: plan.day, memo: t.memo, wallet: t.wallet, mint: t.mint, amount: t.amount });
    try {
      const sig = await chain.send(batch);
      for (const t of batch) append({ event: "transfer", status: "sent", day: plan.day, memo: t.memo, wallet: t.wallet, mint: t.mint, amount: t.amount, sig });
      log("sent", { n: batch.length, sig });
      return true;
    } catch (err) {
      if (err?.tooLarge && batch.length > 1) {
        const h = Math.ceil(batch.length / 2);
        return (await sendBatch(batch.slice(0, h))) && (await sendBatch(batch.slice(h)));
      }
      // Status stays "pending": the next run checks the chain before any retry.
      log("send_failed", { n: batch.length, message: String(err?.message ?? err).slice(0, 200) });
      return false;
    }
  };
  let ok = true;
  for (const b of batches(items, cfg.max_transfers_per_tx)) if (!(ok = await sendBatch(b))) break;

  if (live) writeAtomic(cfg.public_path, JSON.stringify(publicSummary(readLedger(dir), chain.wallet, new Date(now()).toISOString())));
  if (!ok) return 4;
  if (sel.skipped.some((s) => s.reason === "day_cap")) return 3;
  return fit.short.length ? 2 : 0;
}

/** web3.js adapter; loaded only on the server (tests use a mock). */
async function web3Chain(secret, rpcUrl) {
  const w3 = await import("@solana/web3.js");
  const kp = w3.Keypair.fromSecretKey(secret);
  secret.fill(0);
  const conn = new w3.Connection(rpcUrl, "confirmed");
  const me = kp.publicKey;
  const ATA = new w3.PublicKey("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");
  const ata = (owner, mint, prog) =>
    w3.PublicKey.findProgramAddressSync([new w3.PublicKey(owner).toBuffer(), new w3.PublicKey(prog).toBuffer(), new w3.PublicKey(mint).toBuffer()], ATA)[0].toBase58();
  const tx = async (items) => {
    const bh = await conn.getLatestBlockhash("confirmed");
    const t = new w3.Transaction({ feePayer: me, ...bh });
    for (const it of items) {
      for (const d of transferInstructions(it, me.toBase58(), ata)) {
        const keys = d.keys.map((k) => ({ ...k, pubkey: new w3.PublicKey(k.pubkey) }));
        t.add(new w3.TransactionInstruction({ programId: new w3.PublicKey(d.programId), keys, data: Buffer.from(d.data) }));
      }
    }
    t.sign(kp);
    try {
      return { raw: t.serialize(), bh };
    } catch (e) {
      throw Object.assign(new Error(`tx too large: ${e.message}`), { tooLarge: true });
    }
  };
  return {
    wallet: me.toBase58(),
    async mintInfo(mint) {
      const acc = await conn.getParsedAccountInfo(new w3.PublicKey(mint));
      return { programId: acc.value.owner.toBase58(), decimals: acc.value.data.parsed.info.decimals };
    },
    async tokenBalance(mint, prog) {
      const r = await conn.getTokenAccountBalance(new w3.PublicKey(ata(me.toBase58(), mint, prog))).catch(() => null);
      return BigInt(r?.value?.amount ?? 0);
    },
    solBalance: async () => BigInt(await conn.getBalance(me, "confirmed")),
    async missingAtas(items) {
      const keys = items.map((t) => new w3.PublicKey(ata(t.wallet, t.mint, t.programId)));
      let n = 0;
      for (const b of batches(keys, 100)) n += (await conn.getMultipleAccountsInfo(b)).filter((a) => !a).length;
      return n;
    },
    async confirmedMemos() {
      const out = new Map();
      for (const s of await conn.getSignaturesForAddress(me, { limit: 1000 }, "confirmed")) {
        if (s.err || !s.memo) continue;
        for (const m of s.memo.matchAll(/GTASP10:pay:[^;\s]+/g)) out.set(m[0], s.signature);
      }
      return out;
    },
    simulate: async (items) => {
      const r = await conn.simulateTransaction(w3.Transaction.from((await tx(items)).raw));
      return { err: r.value.err ? JSON.stringify(r.value.err) : null };
    },
    send: async (items) => {
      const { raw, bh } = await tx(items);
      const sig = await conn.sendRawTransaction(raw, { skipPreflight: false });
      const c = await conn.confirmTransaction({ signature: sig, ...bh }, "confirmed");
      if (c.value.err) throw new Error(`tx failed ${JSON.stringify(c.value.err)}`);
      return sig;
    },
  };
}

export async function main(argv = process.argv.slice(2)) {
  const arg = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
  const cfgPath = arg("--config", "/etc/coin/payout-bot/config.json");
  const planPath = arg("--plan");
  if (!planPath) throw new Error("--plan is required");
  const cfg = loadConfig(cfgPath);
  if (!cfg.enabled || fs.existsSync(path.join(path.dirname(cfgPath), "STOP"))) {
    defaultLog("stopped", { reason: cfg.enabled ? "STOP file" : "enabled=false" });
    return 0;
  }
  const plan = validatePlan(JSON.parse(fs.readFileSync(planPath, "utf8")));
  const heliusKey = process.env.HELIUS_API_KEY;
  if (!heliusKey) throw new Error("HELIUS_API_KEY is not set");
  fs.mkdirSync(cfg.state_dir, { recursive: true });
  const lock = path.join(cfg.state_dir, "run.lock");
  let fd;
  try {
    fd = fs.openSync(lock, "wx");
  } catch {
    defaultLog("locked");
    return 1;
  }
  try {
    const secret = readSecret(process.env.PAYOUT_BOT_KEYPAIR ?? "/etc/coin/fee-bot/keypair.json");
    const chain = await web3Chain(secret, `https://mainnet.helius-rpc.com/?api-key=${heliusKey}`);
    return await run({ cfg, plan, chain });
  } finally {
    fs.closeSync(fd);
    fs.rmSync(lock, { force: true });
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().then(
    (code) => process.exit(code),
    (err) => {
      defaultLog("error", { message: String(err?.message ?? err).replace(/api-key=[^&\s]+/g, "api-key=***") });
      process.exit(1);
    },
  );
}
