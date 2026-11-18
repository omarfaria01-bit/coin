// Public economic rules (#345): fee split, caps and slippage come only from econ/params.json on
// main. A version applies only when its effective_from has passed AND this server first saw it at
// least `timelock_hours` (72h) earlier, so a new or edited version never takes effect at once:
// until then the bots keep the previous version. No dependencies besides node:.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const ECON_FILE = new URL("./params.json", import.meta.url);
const HOUR_MS = 3_600_000;
const TOP = ["schema", "timelock_hours", "versions"];
const VERSION = ["effective_from", "decisions", "fee_split_bps", "fee_bot", "payout_bot"];
const SPLIT = ["basket", "pot", "burn", "team"];
export const FEE_BOT_KEYS = {
  slippage_bps: "number",
  max_price_impact_pct: "number",
  min_swap_lamports: "string",
  max_per_swap_lamports: "string",
  max_per_run_lamports: "string",
  max_per_day_lamports: "string",
  min_reserve_lamports: "string",
  payout_rent_target_lamports: "string",
};
export const PAYOUT_BOT_KEYS = {
  max_transfers_per_day: "number",
  max_transfers_per_tx: "number",
  min_reserve_lamports: "string",
};

function exactKeys(obj, keys, where) {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) throw new Error(`${where} must be an object`);
  const got = Object.keys(obj).sort().join(",");
  if (got !== [...keys].sort().join(",")) throw new Error(`${where} keys must be exactly ${keys.join(", ")}`);
}

function typed(obj, spec, where) {
  exactKeys(obj, Object.keys(spec), where);
  for (const [k, t] of Object.entries(spec)) {
    const v = obj[k];
    if (t === "number" ? !Number.isInteger(v) || v < 0 : typeof v !== "string" || !/^\d+$/.test(v)) {
      throw new Error(`${where}.${k} must be a ${t === "number" ? "non-negative integer" : "digit string"}`);
    }
  }
}

/** Canonical JSON (sorted keys, no spaces): what the public hash is computed on. */
export function canonical(v) {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") {
    return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
  }
  return JSON.stringify(v);
}

export const versionHash = (v) => crypto.createHash("sha256").update(canonical(v)).digest("hex");

export function validateEcon(doc) {
  exactKeys(doc, TOP, "econ");
  if (doc.schema !== 1) throw new Error("econ schema must be 1");
  if (doc.timelock_hours !== 72) throw new Error("timelock_hours must be 72");
  if (!Array.isArray(doc.versions) || doc.versions.length === 0) throw new Error("econ needs at least one version");
  let prev = -Infinity;
  for (const [i, v] of doc.versions.entries()) {
    const w = `versions[${i}]`;
    exactKeys(v, VERSION, w);
    const t = Date.parse(v.effective_from);
    if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(v.effective_from) || Number.isNaN(t)) {
      throw new Error(`${w}.effective_from must be YYYY-MM-DDTHH:MM:SSZ`);
    }
    if (t <= prev) throw new Error(`${w}.effective_from must be later than the previous version`);
    prev = t;
    if (typeof v.decisions !== "string") throw new Error(`${w}.decisions must be a string`);
    typed(v.fee_split_bps, Object.fromEntries(SPLIT.map((k) => [k, "number"])), `${w}.fee_split_bps`);
    const s = v.fee_split_bps;
    if (s.basket + s.pot + s.burn + s.team !== 10000) throw new Error(`${w}.fee_split_bps must sum to 10000`);
    if (s.team !== 0) throw new Error(`${w}.fee_split_bps.team must be 0`);
    typed(v.fee_bot, FEE_BOT_KEYS, `${w}.fee_bot`);
    if (v.fee_bot.slippage_bps > 300) throw new Error(`${w}.fee_bot.slippage_bps above 300 (3%) is not allowed`);
    typed(v.payout_bot, PAYOUT_BOT_KEYS, `${w}.payout_bot`);
  }
  return doc;
}

/**
 * Pick the version in force at `nowMs`. `seen` maps version hash -> first time this server saw it
 * (ms); null means a fresh install, where versions already effective are the baseline.
 * Returns { active, hash, upcoming, seen } with the updated `seen` map.
 */
export function selectVersion(doc, nowMs, seen) {
  const lock = doc.timelock_hours * HOUR_MS;
  const fresh = seen === null;
  const next = { ...(seen ?? {}) };
  let active = null;
  const upcoming = [];
  for (const v of doc.versions) {
    const hash = versionHash(v);
    const eff = Date.parse(v.effective_from);
    if (!(hash in next)) next[hash] = fresh && eff <= nowMs ? 0 : nowMs;
    const from = next[hash] === 0 ? eff : Math.max(eff, next[hash] + lock);
    if (from <= nowMs) active = { v, hash, from };
    else upcoming.push({ effective_from: new Date(from).toISOString(), sha256: hash });
  }
  if (!active) throw new Error("no econ version in force yet (a new version waits 72h)");
  return { active: active.v, hash: active.hash, upcoming, seen: next };
}

/** Load econ/params.json, apply the timelock with the server's seen-file, and persist it. */
export function loadEcon({ file = ECON_FILE, seenFile, nowMs = Date.now() }) {
  const doc = validateEcon(JSON.parse(fs.readFileSync(file, "utf8")));
  const seen = fs.existsSync(seenFile) ? JSON.parse(fs.readFileSync(seenFile, "utf8")) : null;
  const sel = selectVersion(doc, nowMs, seen);
  fs.mkdirSync(path.dirname(seenFile), { recursive: true });
  const tmp = `${seenFile}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(sel.seen, null, 1));
  fs.renameSync(tmp, seenFile);
  return { ...sel, public: { sha256: sel.hash, effective_from: sel.active.effective_from, upcoming: sel.upcoming } };
}

/**
 * Local config may not set public rules. Caps (`*_lamports` maxima, transfer counts) may only be
 * lowered locally (smoke tests); anything else, or a higher value, is refused.
 */
export function mergeLocal(local, rules, lowerable) {
  const out = { ...rules };
  const tightened = {};
  for (const [k, v] of Object.entries(local)) {
    if (!(k in rules)) continue;
    if (!lowerable.includes(k) || BigInt(v) > BigInt(rules[k])) {
      throw new Error(`${k} is a public rule (econ/params.json, 72h timelock); local config may only lower caps`);
    }
    out[k] = v;
    tightened[k] = v;
  }
  return { rules: out, tightened };
}
