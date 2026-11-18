#!/usr/bin/env node
// GTASP10 fee bot (D45). Collects the coin's creator fees into the system wallet, keeps 30% as
// the SOL pot, buys the index basket with 70% via Jupiter. Runs on the server only.
//
// Safety: the key is read from a 0600 file owned by this user and is never printed; the RPC URL
// (it holds the Helius key) is never printed; hard caps per swap/run/day; slippage and price
// impact gates; kill switch (config.enabled=false or a STOP file); one run at a time (lock);
// "dry" mode does everything except sign and send.
//
// Usage: node run.mjs [--config /etc/coin/fee-bot/config.json]

import fs from "node:fs";
import path from "node:path";

import { createRequire } from "node:module";
import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  VersionedTransaction,
  sendAndConfirmTransaction,
} from "@solana/web3.js";

import {
  applyIncoming,
  applySpent,
  basketFromIndex,
  conserved,
  emptyState,
  owedLamports,
  planBuys,
  quoteAcceptable,
  rentTopUp,
  stateFromJson,
  stateToJson,
} from "./plan.mjs";
import { FEE_BOT_KEYS, loadEcon, mergeLocal } from "../../econ/params.mjs";

// The SDK's ESM build fails to import under Node (anchor is CommonJS); its CJS build works.
const { OnlinePumpSdk } = createRequire(import.meta.url)("@pump-fun/pump-sdk");

const WSOL = "So11111111111111111111111111111111111111112";
const JUP = "https://api.jup.ag/swap/v2";
const CONFIG_KEYS = {
  enabled: "boolean",
  mode: "string", // "dry" | "live"
  fee_mode: "string", // "sharing" | "creator" | "forwarded" (the creator claims and sends SOL from forward_from)
  mint: "string",
  index_max_age_hours: "number",
  index_out_dir: "string",
  state_dir: "string",
  public_log_path: "string",
};

const log = (event, data = {}) => console.log(JSON.stringify({ t: new Date().toISOString(), event, ...data }));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Caps a local config may lower (smoke test), never raise. Every other rule is public only.
const LOWERABLE = ["max_per_swap_lamports", "max_per_run_lamports", "max_per_day_lamports"];

/**
 * Local config (paths, mode, mint) + the public rules in force (#345): split, caps and slippage
 * come from econ/params.json with its 72h timelock. Returns the merged config and `econ` info.
 */
export function loadConfig(file, { econFile, seenFile, nowMs } = {}) {
  const local = JSON.parse(fs.readFileSync(file, "utf8"));
  const own = {};
  for (const [k, v] of Object.entries(local)) {
    if (k in FEE_BOT_KEYS) continue; // checked by mergeLocal below
    if (k === "pot_bps" || k === "burn_bps") throw new Error(`${k} is a public rule (econ/params.json, 72h timelock)`);
    if (k === "forward_from") continue; // checked below
    if (!(k in CONFIG_KEYS)) throw new Error(`unknown config key ${k}`);
    own[k] = v;
  }
  for (const [k, t] of Object.entries(CONFIG_KEYS)) {
    if (typeof own[k] !== t) throw new Error(`config ${k} must be ${t}`);
  }
  if (!["dry", "live"].includes(own.mode)) throw new Error("mode must be dry or live");
  if (!["sharing", "creator", "forwarded"].includes(own.fee_mode)) throw new Error("fee_mode must be sharing, creator or forwarded");
  if ((own.fee_mode === "forwarded") !== ("forward_from" in local)) throw new Error("forward_from is required with fee_mode forwarded, and only then");
  if (own.fee_mode === "forwarded") own.forward_from = new PublicKey(local.forward_from).toBase58();
  new PublicKey(own.mint); // throws on a bad mint
  const econ = loadEcon({ file: econFile, seenFile: seenFile ?? path.join(own.state_dir, "econ_seen.json"), nowMs });
  const local_rules = Object.fromEntries(Object.entries(local).filter(([k]) => k in FEE_BOT_KEYS));
  const { rules, tightened } = mergeLocal(local_rules, econ.active.fee_bot, LOWERABLE);
  const split = econ.active.fee_split_bps;
  return { ...own, ...rules, pot_bps: split.pot, burn_bps: split.burn, econ: { ...econ.public, local_lower_caps: tightened } };
}

/** Read the keypair only from a private file owned by this user. Never logs it. */
export function loadKeypair(file) {
  const st = fs.statSync(file);
  if ((st.mode & 0o077) !== 0) throw new Error("keypair file must be chmod 600");
  if (typeof process.getuid === "function" && st.uid !== process.getuid()) {
    throw new Error("keypair file must be owned by the bot user");
  }
  const raw = Uint8Array.from(JSON.parse(fs.readFileSync(file, "utf8")));
  if (raw.length !== 64) throw new Error("keypair file is not a 64-byte secret key");
  // fromSecretKey keeps a reference to the array it gets, so pass a copy before zeroing ours.
  const kp = Keypair.fromSecretKey(Uint8Array.from(raw));
  raw.fill(0);
  return kp;
}

function writeAtomic(file, text) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, text, { mode: 0o644 });
  fs.renameSync(tmp, file);
}

function loadState(dir) {
  const f = path.join(dir, "state.json");
  return fs.existsSync(f) ? stateFromJson(JSON.parse(fs.readFileSync(f, "utf8"))) : emptyState();
}

function saveState(dir, s) {
  if (!conserved(s)) throw new Error("state not conserved, refusing to save");
  writeAtomic(path.join(dir, "state.json"), JSON.stringify(stateToJson(s), null, 1));
}

function ledger(dir, entry) {
  fs.appendFileSync(path.join(dir, "ledger.jsonl"), `${JSON.stringify(entry)}\n`);
}

function latestIndex(dir) {
  const files = fs
    .readdirSync(dir)
    .filter((f) => /^\d{4}-\d\d-\d\dT\d\d\.json$/.test(f))
    .sort();
  if (files.length === 0) return null;
  return JSON.parse(fs.readFileSync(path.join(dir, files.at(-1)), "utf8"));
}

async function jup(pathAndQuery, init = {}) {
  const headers = { "content-type": "application/json" };
  if (process.env.JUP_API_KEY) headers["x-api-key"] = process.env.JUP_API_KEY;
  const res = await fetch(`${JUP}${pathAndQuery}`, { ...init, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`jupiter ${res.status} ${body.error ?? ""}`.trim());
  return body;
}

async function sendIxs(connection, wallet, ixs) {
  const tx = new Transaction().add(...ixs);
  const sig = await sendAndConfirmTransaction(connection, tx, [wallet], { commitment: "confirmed" });
  const info = await connection.getTransaction(sig, { commitment: "confirmed", maxSupportedTransactionVersion: 0 });
  return { sig, fee: BigInt(info?.meta?.fee ?? 0) };
}

/** Step 1: move the coin's creator fees into the system wallet. Returns lamports received. */
/**
 * fee_mode "forwarded" (pump.fun legacy rewards can't be shared): the creator claims and sends SOL from
 * `forward_from`. Counts plain system transfers forward_from -> this wallet since the cursor. The first
 * run only sets the cursor (earlier deposits, e.g. the reserve, are not fees). Dry mode never moves it.
 */
export function forwardedLamports(txs, from, to) {
  let total = 0n;
  const sigs = [];
  for (const { sig, tx } of txs) {
    if (!tx || tx.meta?.err) continue;
    for (const ix of tx.transaction?.message?.instructions ?? []) {
      const info = ix.parsed?.info;
      if (ix.program === "system" && ix.parsed?.type === "transfer" && info?.source === from && info?.destination === to) {
        total += BigInt(info.lamports);
        sigs.push(sig);
      }
    }
  }
  return { total, sigs };
}

async function collectForwarded(cfg, connection, wallet, cursor) {
  const me = wallet.publicKey.toBase58();
  const list = await connection.getSignaturesForAddress(wallet.publicKey, { until: cursor && cursor !== "START" ? cursor : undefined, limit: 1000 }, "confirmed");
  const txs = [];
  for (const s of [...list].reverse()) {
    if (s.err) continue;
    txs.push({ sig: s.signature, tx: await connection.getParsedTransaction(s.signature, { commitment: "confirmed", maxSupportedTransactionVersion: 0 }) });
  }
  const { total, sigs } = forwardedLamports(txs, cfg.forward_from, me);
  log("forwarded", { lamports: String(total), sigs });
  if (cfg.mode === "dry") return { received: 0n };
  // First run (no cursor) counts the whole history: forwards sent before the bot started are owed too.
  return { received: total, sig: sigs.join(","), cursor: list[0]?.signature ?? cursor ?? "START" };
}

async function collect(cfg, connection, sdk, wallet, cursor) {
  if (cfg.fee_mode === "forwarded") return collectForwarded(cfg, connection, wallet, cursor);
  const mint = new PublicKey(cfg.mint);
  let ixs;
  if (cfg.fee_mode === "sharing") {
    const min = await sdk.getMinimumDistributableFee(mint, wallet.publicKey);
    log("distributable", { can: Boolean(min.canDistribute), fees: String(min.distributableFees ?? "") });
    if (!min.canDistribute) return { received: 0n };
    ({ instructions: ixs } = await sdk.buildDistributeCreatorFeesInstructions(mint, { payer: wallet.publicKey }));
  } else {
    const vault = BigInt((await sdk.getCreatorVaultBalanceBothPrograms(wallet.publicKey)).toString());
    log("creator_vault", { lamports: String(vault) });
    if (vault === 0n) return { received: 0n };
    ixs = await sdk.collectCoinCreatorFeeInstructions(wallet.publicKey, wallet.publicKey);
  }
  if (cfg.mode === "dry") {
    log("dry_collect", { instructions: ixs.length });
    return { received: 0n };
  }
  const before = BigInt(await connection.getBalance(wallet.publicKey, "confirmed"));
  const { sig, fee } = await sendIxs(connection, wallet, ixs);
  const after = BigInt(await connection.getBalance(wallet.publicKey, "confirmed"));
  const received = after - before + fee; // the tx fee is paid from the reserve, not from the fees
  log("collected", { sig, lamports: String(received) });
  return { received: received > 0n ? received : 0n, sig };
}

/** Step 3: one Jupiter swap SOL -> member. Returns lamports actually spent, or 0n. */
async function buy(cfg, wallet, mint, lamports) {
  const q = new URLSearchParams({
    inputMint: WSOL,
    outputMint: mint,
    amount: lamports.toString(),
    taker: wallet.publicKey.toBase58(),
    slippageBps: String(cfg.slippage_bps),
  });
  const order = await jup(`/order?${q}`);
  if (!quoteAcceptable(order, cfg.slippage_bps, cfg.max_price_impact_pct)) {
    log("quote_refused", { mint, slippageBps: order.slippageBps, priceImpact: order.priceImpact, err: order.errorCode });
    return { spent: 0n };
  }
  if (cfg.mode === "dry") {
    log("dry_buy", { mint, lamports: lamports.toString(), outAmount: order.outAmount, router: order.router });
    return { spent: 0n };
  }
  const tx = VersionedTransaction.deserialize(Buffer.from(order.transaction, "base64"));
  tx.sign([wallet]);
  const res = await jup("/execute", {
    method: "POST",
    body: JSON.stringify({ signedTransaction: Buffer.from(tx.serialize()).toString("base64"), requestId: order.requestId }),
  });
  if (res.status !== "Success") {
    log("buy_failed", { mint, code: res.code, error: res.error, sig: res.signature });
    return { spent: 0n, failed: true };
  }
  const spent = BigInt(res.totalInputAmount ?? res.inputAmountResult ?? lamports);
  log("bought", { mint, sig: res.signature, spent: spent.toString(), out: String(res.totalOutputAmount ?? "") });
  return { spent: spent > lamports ? lamports : spent, sig: res.signature, out: String(res.totalOutputAmount ?? "") };
}

export async function main(argv = process.argv.slice(2)) {
  const cfgPath = argv[0] === "--config" ? argv[1] : "/etc/coin/fee-bot/config.json";
  const cfg = loadConfig(cfgPath);
  const stopFile = path.join(path.dirname(cfgPath), "STOP");
  if (!cfg.enabled || fs.existsSync(stopFile)) {
    log("stopped", { reason: cfg.enabled ? "STOP file" : "enabled=false" });
    return 0;
  }
  const key = process.env.HELIUS_API_KEY;
  if (!key) throw new Error("HELIUS_API_KEY is not set");
  const keyFile = process.env.FEE_BOT_KEYPAIR ?? "/etc/coin/fee-bot/keypair.json";

  fs.mkdirSync(cfg.state_dir, { recursive: true });
  const lock = path.join(cfg.state_dir, "run.lock");
  let fd;
  try {
    fd = fs.openSync(lock, "wx");
  } catch {
    log("locked");
    return 1;
  }
  try {
    const wallet = loadKeypair(keyFile);
    log("start", { mode: cfg.mode, fee_mode: cfg.fee_mode, forward_from: cfg.forward_from ?? null, wallet: wallet.publicKey.toBase58(), mint: cfg.mint, econ: cfg.econ });
    const connection = new Connection(`https://mainnet.helius-rpc.com/?api-key=${key}`, "confirmed");
    const sdk = new OnlinePumpSdk(connection);
    let state = loadState(cfg.state_dir);
    const day = new Date().toISOString().slice(0, 10);

    // Reserve check: the wallet must hold pot + basket + a reserve for tx fees and rent.
    const balance = BigInt(await connection.getBalance(wallet.publicKey, "confirmed"));
    const owed = owedLamports(state);
    if (balance < owed + BigInt(cfg.min_reserve_lamports)) {
      log("low_reserve", { balance: String(balance), owed: String(owed), reserve: cfg.min_reserve_lamports });
      ledger(cfg.state_dir, { t: Date.now(), event: "low_reserve" });
      return 2;
    }

    const got = await collect(cfg, connection, sdk, wallet, state.forwardCursor);
    if (got.cursor !== undefined && got.cursor !== state.forwardCursor && got.received === 0n) {
      state = { ...state, forwardCursor: got.cursor };
      saveState(cfg.state_dir, state);
    }
    if (got.received > 0n) {
      if (got.cursor !== undefined) state = { ...state, forwardCursor: got.cursor };
      // D49: the burn share is held (burnLamports) until buyback & burn ships (#344); never spent otherwise.
      state = applyIncoming(state, got.received, BigInt(cfg.pot_bps), BigInt(cfg.burn_bps));
      saveState(cfg.state_dir, state);
      ledger(cfg.state_dir, { t: Date.now(), event: "collected", sig: got.sig, lamports: String(got.received) });
    }

    // D46: holders' new token accounts are paid from the basket budget, before buying, within
    // the day cap; the payout sender only spends SOL above pot + basket + reserve.
    const free = balance - owed - BigInt(cfg.min_reserve_lamports);
    const spentToday = state.dayKey === day ? state.spentTodayLamports : 0n;
    const maxDay = BigInt(cfg.max_per_day_lamports);
    const topUp = rentTopUp(state.basketLamports, free, BigInt(cfg.payout_rent_target_lamports), maxDay > spentToday ? maxDay - spentToday : 0n);
    if (topUp > 0n && cfg.mode === "live") {
      state = applySpent(state, topUp, day);
      saveState(cfg.state_dir, state);
      ledger(cfg.state_dir, { t: Date.now(), event: "payout_rent", lamports: String(topUp) });
      log("payout_rent", { lamports: String(topUp), free_before: String(free) });
    }

    const basket = basketFromIndex(
      latestIndex(cfg.index_out_dir),
      Date.now(),
      cfg.index_max_age_hours * 3_600_000,
      cfg.mint,
    );
    if (!basket.ok) {
      log("no_buy", { reason: basket.reason });
    } else {
      const plan = planBuys(state.basketLamports, basket.members, {
        maxPerRun: BigInt(cfg.max_per_run_lamports),
        maxPerSwap: BigInt(cfg.max_per_swap_lamports),
        minSwap: BigInt(cfg.min_swap_lamports),
        maxPerDay: BigInt(cfg.max_per_day_lamports),
        spentToday: state.dayKey === day ? state.spentTodayLamports : 0n,
      });
      log("plan", { buys: plan.buys.map((b) => [b.mint, b.lamports.toString()]), carry: plan.carry.toString() });
      for (const b of plan.buys) {
        const r = await buy(cfg, wallet, b.mint, b.lamports);
        if (r.spent > 0n) {
          state = applySpent(state, r.spent, day);
          saveState(cfg.state_dir, state);
          ledger(cfg.state_dir, { t: Date.now(), event: "bought", mint: b.mint, sig: r.sig, spent: String(r.spent), out: r.out });
        }
        if (r.failed) break; // stop the run on a failed swap; next run retries
        await sleep(2500); // keyless Jupiter limit is 0.5 RPS
      }
    }

    const pub = { as_of: new Date().toISOString(), wallet: wallet.publicKey.toBase58(), mode: cfg.mode, fee_mode: cfg.fee_mode, forward_from: cfg.forward_from ?? null, econ: cfg.econ, ...stateToJson(state) };
    if (cfg.public_log_path) writeAtomic(cfg.public_log_path, JSON.stringify(pub));
    log("done", pub);
    return 0;
  } finally {
    fs.closeSync(fd);
    fs.rmSync(lock, { force: true });
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().then(
    (code) => process.exit(code),
    (err) => {
      // Error messages never include the key or the RPC URL (fetch errors are summarised).
      log("error", { message: String(err?.message ?? err).replace(/api-key=[^&\s]+/g, "api-key=***") });
      process.exit(1);
    },
  );
}
