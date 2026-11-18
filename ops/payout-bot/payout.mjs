// GTASP10 payout sender core (D46). No I/O, no dependencies: plan validation, idempotency,
// caps, batching and instruction layout. The chain is reached only through the injected `chain`.

export const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
export const TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";
export const ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL";
export const MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr";
export const SYSTEM_PROGRAM = "11111111111111111111111111111111";
export const ATA_RENT_LAMPORTS = 2_100_000n; // >= rent of a Token-2022 ATA (170 bytes); SPL needs 2_039_280
export const TX_FEE_LAMPORTS = 10_000n;
export const PENDING_RETRY_MS = 5 * 60_000; // a blockhash is dead after ~90 s; 5 min is safe

const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const INT = /^(0|[1-9]\d*)$/;

/** True when s is base58 that decodes to exactly 32 bytes (a Solana public key). */
export function isPubkey(s) {
  if (typeof s !== "string" || s.length < 32 || s.length > 44) return false;
  let n = 0n;
  for (const c of s) {
    const d = B58.indexOf(c);
    if (d < 0) return false;
    n = n * 58n + BigInt(d);
  }
  let bytes = s.length - s.replace(/^1+/, "").length; // leading '1' = zero byte
  for (; n > 0n; n >>= 8n) bytes++;
  return bytes === 32;
}

const fail = (msg) => {
  throw new Error(`plan: ${msg}`);
};
const keysOnly = (o, keys, where) => {
  if (!o || typeof o !== "object" || Array.isArray(o)) fail(`${where} must be an object`);
  for (const k of Object.keys(o)) if (!keys.includes(k)) fail(`unknown key ${where}.${k}`);
  for (const k of keys) if (!(k in o)) fail(`missing ${where}.${k}`);
};
const pk = (s, where) => isPubkey(s) || fail(`${where} is not a pubkey`);
const amt = (s, where, min = 0n) => {
  if (typeof s !== "string" || !INT.test(s)) fail(`${where} must be an integer string`);
  if (BigInt(s) < min) fail(`${where} must be >= ${min}`);
  return BigInt(s);
};

/** Validate payout-plan.json (schema 1, contract in #314/#316). Returns the plan or throws. */
export function validatePlan(p) {
  keysOnly(p, ["schema", "day", "system_wallet", "transfers", "carried", "excluded", "totals"], "plan");
  if (p.schema !== 1) fail("schema must be 1");
  if (!/^\d{4}-\d\d-\d\d$/.test(p.day)) fail("day must be YYYY-MM-DD");
  pk(p.system_wallet, "system_wallet");
  for (const k of ["transfers", "carried", "excluded"]) if (!Array.isArray(p[k])) fail(`${k} must be an array`);
  const paid = new Map();
  const carried = new Map();
  const memos = new Set();
  const excluded = new Set();
  p.excluded.forEach((e, i) => {
    keysOnly(e, ["wallet", "reason"], `excluded[${i}]`);
    pk(e.wallet, `excluded[${i}].wallet`);
    if (!["team", "system", "pool", "burn", "cex"].includes(e.reason)) fail(`excluded[${i}].reason`);
    excluded.add(e.wallet);
  });
  p.transfers.forEach((t, i) => {
    const w = `transfers[${i}]`;
    keysOnly(t, ["wallet", "mint", "amount", "memo"], w);
    pk(t.wallet, `${w}.wallet`);
    pk(t.mint, `${w}.mint`);
    const a = amt(t.amount, `${w}.amount`, 1n);
    if (t.memo !== `GTASP10:pay:${p.day}:${t.wallet}:${t.mint}`) fail(`${w}.memo does not match day/wallet/mint`);
    if (memos.has(t.memo)) fail(`${w} duplicate memo`);
    if (excluded.has(t.wallet) || t.wallet === p.system_wallet) fail(`${w} pays an excluded wallet`);
    memos.add(t.memo);
    paid.set(t.mint, (paid.get(t.mint) ?? 0n) + a);
  });
  p.carried.forEach((c, i) => {
    keysOnly(c, ["wallet", "mint", "amount"], `carried[${i}]`);
    pk(c.wallet, `carried[${i}].wallet`);
    pk(c.mint, `carried[${i}].mint`);
    carried.set(c.mint, (carried.get(c.mint) ?? 0n) + amt(c.amount, `carried[${i}].amount`));
  });
  if (!p.totals || typeof p.totals !== "object") fail("totals must be an object");
  const mints = new Set([...paid.keys(), ...carried.keys(), ...Object.keys(p.totals)]);
  for (const m of mints) {
    pk(m, `totals key ${m}`);
    const t = p.totals[m] ?? fail(`totals missing ${m}`);
    keysOnly(t, ["accrued", "paid", "carried"], `totals.${m}`);
    const [ac, pd, ca] = ["accrued", "paid", "carried"].map((k) => amt(t[k], `totals.${m}.${k}`));
    if (pd + ca !== ac) fail(`totals.${m}: paid + carried != accrued`);
    if (pd !== (paid.get(m) ?? 0n)) fail(`totals.${m}.paid != sum of transfers`);
    if (ca !== (carried.get(m) ?? 0n)) fail(`totals.${m}.carried != sum of carried`);
  }
  return p;
}

/** Fold ledger lines into memo -> latest status entry. */
export function memoStatus(ledgerEntries) {
  const out = new Map();
  for (const e of ledgerEntries) if (e.memo && e.status !== "dry") out.set(e.memo, e);
  return out;
}

/**
 * Decide what this run may send. `onChain` is a Map memo -> signature of confirmed, successful txs.
 * Returns { todo, done: [{memo, sig}], skipped: [{memo, reason}] }.
 */
export function selectTodo(plan, ledgerEntries, onChain, now, caps) {
  const status = memoStatus(ledgerEntries);
  const done = [];
  const skipped = [];
  let todo = [];
  for (const t of plan.transfers) {
    const e = status.get(t.memo);
    if (e?.status === "sent") continue;
    if (onChain.has(t.memo)) {
      done.push({ ...t, sig: onChain.get(t.memo) });
      continue;
    }
    if (e?.status === "pending" && now - e.t < PENDING_RETRY_MS) {
      skipped.push({ memo: t.memo, reason: "pending" });
      continue;
    }
    todo.push(t);
  }
  const sentToday = [...status.values()].filter((e) => e.status === "sent" && e.day === plan.day);
  const room = Math.max(0, caps.maxTransfersPerDay - sentToday.length - done.length);
  for (const t of todo.slice(room)) skipped.push({ memo: t.memo, reason: "day_cap" });
  todo = todo.slice(0, room);
  return { todo, done, skipped };
}

/** Group transfers by mint and drop any mint whose total exceeds what the wallet holds. */
export function fitBalances(todo, balances) {
  const need = new Map();
  for (const t of todo) need.set(t.mint, (need.get(t.mint) ?? 0n) + BigInt(t.amount));
  const short = [...need].filter(([m, n]) => n > (balances.get(m) ?? 0n)).map(([m]) => m);
  return { ok: todo.filter((t) => !short.includes(t.mint)), short };
}

/** Lamports this run spends: rent for missing ATAs plus tx fees, given batch size. */
export function solNeeded(todo, missingAtas, perTx) {
  return BigInt(missingAtas) * ATA_RENT_LAMPORTS + BigInt(Math.ceil(todo.length / perTx)) * TX_FEE_LAMPORTS;
}

export function batches(list, size) {
  const out = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

const u64le = (n) => {
  const b = new Uint8Array(8);
  let v = BigInt(n);
  for (let i = 0; i < 8; i++, v >>= 8n) b[i] = Number(v & 0xffn);
  return b;
};

/**
 * Instruction descriptors for one transfer: create-idempotent ATA, TransferChecked, memo.
 * `t` carries {wallet, mint, amount, memo, programId, decimals}; `ata(owner, mint, program)` derives.
 */
export function transferInstructions(t, payer, ata) {
  if (![TOKEN, TOKEN_2022].includes(t.programId)) throw new Error(`unknown token program for ${t.mint}`);
  const src = ata(payer, t.mint, t.programId);
  const dst = ata(t.wallet, t.mint, t.programId);
  const m = (pubkey, isSigner, isWritable) => ({ pubkey, isSigner, isWritable });
  return [
    {
      programId: ATA_PROGRAM,
      keys: [m(payer, true, true), m(dst, false, true), m(t.wallet, false, false), m(t.mint, false, false), m(SYSTEM_PROGRAM, false, false), m(t.programId, false, false)],
      data: Uint8Array.of(1), // CreateIdempotent
    },
    {
      programId: t.programId,
      keys: [m(src, false, true), m(t.mint, false, false), m(dst, false, true), m(payer, true, false)],
      data: Uint8Array.from([12, ...u64le(t.amount), t.decimals]), // TransferChecked
    },
    { programId: MEMO_PROGRAM, keys: [m(payer, true, false)], data: new TextEncoder().encode(t.memo) },
  ];
}

/** Public payouts.json, rebuilt from the whole ledger. */
export function publicSummary(ledgerEntries, wallet, asOf) {
  const days = new Map();
  const day = (d) => {
    if (!days.has(d)) days.set(d, { day: d, transfers: [], carried_total: {}, excluded: [] });
    return days.get(d);
  };
  for (const e of ledgerEntries) {
    if (e.event === "plan") Object.assign(day(e.day), { carried_total: e.carried_total, excluded: e.excluded });
  }
  for (const e of memoStatus(ledgerEntries).values()) {
    if (e.status === "sent") day(e.day).transfers.push({ wallet: e.wallet, mint: e.mint, amount: e.amount, sig: e.sig });
  }
  return { as_of: asOf, wallet, days: [...days.values()].sort((a, b) => (a.day < b.day ? 1 : -1)) };
}
