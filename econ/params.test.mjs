import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { ECON_FILE, canonical, loadEcon, mergeLocal, selectVersion, validateEcon, versionHash } from "./params.mjs";

const H = 3_600_000;
const doc = JSON.parse(fs.readFileSync(ECON_FILE, "utf8"));
const v0 = doc.versions[0];
const T0 = Date.parse(v0.effective_from);
const withNew = (eff, change) => ({
  ...doc,
  versions: [v0, { ...v0, effective_from: eff, fee_split_bps: { ...v0.fee_split_bps, ...change } }],
});

test("the published file is valid: D50 split, team 0, slippage <= 3%", () => {
  validateEcon(doc);
  assert.deepEqual(v0.fee_split_bps, { basket: 7000, pot: 3000, burn: 0, team: 0 });
  const bad = (f, re) => {
    const d = structuredClone(doc);
    f(d);
    assert.throws(() => validateEcon(d), re);
  };
  bad((d) => (d.versions[0].fee_split_bps.team = 1), /sum to 10000|team/);
  bad((d) => Object.assign(d.versions[0].fee_split_bps, { team: 100, basket: 6600 }), /team must be 0/);
  bad((d) => (d.versions[0].fee_bot.slippage_bps = 301), /slippage/);
  bad((d) => (d.versions[0].fee_bot.extra = 1), /keys must be exactly/);
  bad((d) => (d.timelock_hours = 1), /72/);
  bad((d) => d.versions.push({ ...d.versions[0] }), /later than the previous/);
});

test("hash is over canonical JSON, independent of key order", () => {
  assert.equal(canonical({ b: 1, a: [2, { d: 3, c: 4 }] }), '{"a":[2,{"c":4,"d":3}],"b":1}');
  const shuffled = Object.fromEntries(Object.entries(v0).reverse());
  assert.equal(versionHash(shuffled), versionHash(v0));
});

test("fresh install: versions already effective are the baseline", () => {
  const s = selectVersion(doc, T0 + H, null);
  assert.equal(s.hash, versionHash(v0));
  assert.deepEqual(s.upcoming, []);
});

test("a new version is ignored for 72h after the server first sees it, then applies", () => {
  const seen = selectVersion(doc, T0 + H, null).seen;
  const pushed = T0 + 10 * H;
  // effective_from already in the past when pushed: still waits 72h from first sight
  const d = withNew(new Date(T0 + 2 * H).toISOString().replace(".000", ""), { pot: 3800, basket: 5700 });
  const a = selectVersion(d, pushed, seen);
  assert.equal(a.active, v0);
  assert.equal(a.upcoming.length, 1);
  assert.equal(Date.parse(a.upcoming[0].effective_from), pushed + 72 * H);
  assert.equal(selectVersion(d, pushed + 72 * H - 1, a.seen).active, v0);
  assert.equal(selectVersion(d, pushed + 72 * H, a.seen).active.fee_split_bps.pot, 3800);
});

test("editing the version in force is a new version: the old one stays until 72h pass", () => {
  const seen = selectVersion(doc, T0 + H, null).seen;
  const edited = { ...doc, versions: [{ ...v0, fee_split_bps: { ...v0.fee_split_bps, pot: 3800, basket: 5700 } }] };
  assert.throws(() => selectVersion(edited, T0 + 2 * H, seen), /no econ version in force/);
});

test("loadEcon persists first-seen times; mergeLocal only lowers caps", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "econ-"));
  const seenFile = path.join(dir, "seen.json");
  const e = loadEcon({ seenFile, nowMs: T0 + H });
  assert.equal(e.public.sha256, versionHash(v0));
  assert.deepEqual(JSON.parse(fs.readFileSync(seenFile, "utf8")), { [versionHash(v0)]: 0 });
  const rules = { max_per_run_lamports: "100", slippage_bps: 300 };
  assert.deepEqual(mergeLocal({ max_per_run_lamports: "5" }, rules, ["max_per_run_lamports"]).tightened, {
    max_per_run_lamports: "5",
  });
  assert.throws(() => mergeLocal({ max_per_run_lamports: "101" }, rules, ["max_per_run_lamports"]), /public rule/);
  assert.throws(() => mergeLocal({ slippage_bps: 100 }, rules, ["max_per_run_lamports"]), /public rule/);
});
