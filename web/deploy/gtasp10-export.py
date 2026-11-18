#!/usr/bin/env python3
"""GTASP10 public site data export. Read-only on coin data; writes only /var/www/gtasp10/data."""

import glob
import json
import os
import re
import tempfile
import time

OUT_DIR = "/var/lib/coin/index-data/index/out"
SAMPLES = "/opt/coin/data/index/samples"
DEST = "/var/www/gtasp10/data"
os.makedirs(DEST, exist_ok=True)


def write(name, obj):
    fd, tmp = tempfile.mkstemp(dir=DEST)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(DEST, name))


HOURLY = re.compile(r"\d{4}-\d\d-\d\dT\d\d\.json$")
outs = sorted(p for p in glob.glob(OUT_DIR + "/*.json") if HOURLY.search(p))
latest = {}
if outs:
    with open(outs[-1]) as f:
        latest = json.load(f)
    latest["_file"] = os.path.basename(outs[-1])
    write("latest.json", latest)

tickers = {}
for p in outs[-3:]:
    try:
        with open(p) as f:
            d = json.load(f)
    except Exception:
        continue
    for e in d.get("excluded", []) + d.get("members", []):
        if e.get("ticker"):
            tickers[e["mint"]] = e["ticker"]
reasons = {e["mint"]: e.get("reason") for e in latest.get("excluded", [])}
members = {m["mint"] for m in latest.get("members", [])}

last = {}
for p in sorted(glob.glob(SAMPLES + "/*.jsonl"))[-2:]:
    with open(p) as f:
        for line in f:
            try:
                s = json.loads(line)
            except Exception:
                continue
            m = s.get("mint")
            if not m:
                continue
            prev = last.get(m)
            if prev is None or s.get("t", 0) >= prev.get("t", 0):
                # keep last non-null liquidity if newest sample lacks it
                if prev and s.get("liquidity_usd") is None:
                    s["liquidity_usd"] = prev.get("liquidity_usd")
                last[m] = s
now = time.time()
cands = []
for m, s in last.items():
    if now - s.get("t", 0) > 6 * 3600:
        continue
    cands.append(
        {
            "mint": m,
            "ticker": tickers.get(m),
            "mc": s.get("mc_usd"),
            "liq": s.get("liquidity_usd"),
            "vol24h": s.get("volume_usd"),
            "t": s.get("t"),
            "status": "member" if m in members else reasons.get(m),
        }
    )
cands.sort(key=lambda c: -(c["mc"] or 0))
write("candidates.json", {"generated": int(now), "count": len(cands), "candidates": cands[:100]})
