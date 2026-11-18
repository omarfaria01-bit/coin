(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const DATA = "data/";
  const RELEASE = new Date(2026, 10, 19, 0, 0, 0); // 19 Nov 2026 00:00 local time
  let latest = null, cands = null, sortKey = "vol24h";


  const t = {asof:"Last run", days:"d", none:"No candidate with enough data", member:"member", nodata:"collecting data",
        cols:["#","Coin","Status","Market cap","Liquidity","Vol 24h"], mcols:["#","Coin","Weight","Market cap","Liquidity","Volume","Δ"],
        excl:(n,r)=>`${n} candidates evaluated, ${r} waiting for data`, out:"GTA 6 is out!", newb:"new"};

  const REASON = {insufficient_data:"collecting data",F1:"too young",F2:"liquidity < $50k",F3:"top holders outside 13–27%",F4:"fees < 8 SOL",F5:"bundle > 30%",F7:"serial creator",F8:"authorities active",F8c:"token program",F9:"< 200 traders",F10:"zero volume",F11:"MC > 100× liq",deny:"excluded (scam)"};


  // i18n


  // formatting
  const usd = (v) => {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
    return "$" + v.toFixed(0);
  };
  const short = (m) => m.slice(0, 4) + "…" + m.slice(-4);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");

  // countdowns
  function tick() {
    const now = new Date();
    let d = RELEASE - now;
    if (d <= 0) $("#cd-release").textContent = t.out;
    else {
      const days = Math.floor(d / 864e5); d -= days * 864e5;
      const h = Math.floor(d / 36e5); d -= h * 36e5;
      const m = Math.floor(d / 6e4); const s = Math.floor((d - m * 6e4) / 1e3);
      $("#cd-release").textContent = (days ? days + t.days + " " : "") + `${pad(h)}:${pad(m)}:${pad(s)}`;
    }
    const next = new Date(now); next.setMinutes(60, 0, 0);
    const r = next - now, mm = Math.floor(r / 6e4), ss = Math.floor((r % 6e4) / 1e3);
    const txt = `${pad(mm)}:${pad(ss)}`;
    $("#cd-hour").textContent = txt; $("#cd-hour2").textContent = txt;
  }
  setInterval(tick, 1000); tick();

  // charts
  function curve() {
    const pts = [[0,0],[1,0],[1,1],[1.5,1],[1.75,1.5],[2,2],[2.5,3],[3,4],[4,5],[5,5]];
    const W = 640, H = 260, L = 44, R = 20, Tp = 20, B = 36;
    const x = (h) => L + (h / 5) * (W - L - R), y = (m) => H - B - (m / 5) * (H - Tp - B);
    let s = `<defs><linearGradient id="cg" x1="0" x2="1"><stop offset="0" stop-color="#ff2d95"/><stop offset=".6" stop-color="#ff8a3d"/><stop offset="1" stop-color="#ffd166"/></linearGradient>
      <linearGradient id="cf" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ff2d95" stop-opacity=".35"/><stop offset="1" stop-color="#ff2d95" stop-opacity="0"/></linearGradient>
      <filter id="gl"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
    for (let m = 0; m <= 5; m++) s += `<line x1="${L}" x2="${W - R}" y1="${y(m)}" y2="${y(m)}" stroke="#ffffff14"/><text x="${L - 10}" y="${y(m) + 4}" text-anchor="end">${m}×</text>`;
    for (let h = 0; h <= 5; h++) s += `<text x="${x(h)}" y="${H - 12}" text-anchor="middle">${h}h</text>`;
    const d = pts.map((p, i) => (i ? "L" : "M") + x(p[0]) + " " + y(p[1])).join(" ");
    s += `<path d="${d} L${x(5)} ${y(0)} L${x(0)} ${y(0)}Z" fill="url(#cf)"/>`;
    s += `<path d="${d}" fill="none" stroke="url(#cg)" stroke-width="4" stroke-linejoin="round" filter="url(#gl)"/>`;
    [[1,1],[1.75,1.5],[2,2],[2.5,3],[3,4],[4,5]].forEach(([h, m]) => {
      s += `<circle cx="${x(h)}" cy="${y(m)}" r="5" fill="#fff" stroke="#ff2d95" stroke-width="3"/><text class="lab" x="${x(h) - 6}" y="${y(m) - 12}" text-anchor="middle">${m}×</text>`;
    });
    $("#curve").innerHTML = s;
  }
  curve();

  const COLORS = ["#ff2d95","#ff8a3d","#ffd166","#8b5cf6","#22e3ff","#ff4fd8","#4ade80","#f472b6","#fb923c","#a78bfa"];
  function donut(members) {
    const total = members.reduce((a, m) => a + (m.weight_bps || 0), 0) || 1;
    const r = 80, c = 2 * Math.PI * r; let off = 0, s = "";
    members.forEach((m, i) => {
      const f = (m.weight_bps || 0) / total;
      s += `<circle cx="110" cy="110" r="${r}" fill="none" stroke="${COLORS[i % 10]}" stroke-width="30" stroke-dasharray="${f * c} ${c}" stroke-dashoffset="${-off * c}" transform="rotate(-90 110 110)"><title>${esc(m.ticker)} ${(f * 100).toFixed(1)}%</title></circle>`;
      off += f;
    });
    $("#donut").innerHTML = s; $("#donut-n").textContent = members.length;
  }

  function render() {
    if (!latest && !cands) return;
    if (latest) {
      const asof = latest.as_of ? new Date(latest.as_of) : null;
      $("#asof").textContent = asof ? `${t.asof}: ${asof.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}${latest.dry_run ? " · dry-run" : ""}` : "";
      $("#hashes").textContent = latest.params_hash ? `params ${latest.params_hash.slice(0, 16)}… · inputs ${(latest.inputs_hash || "").slice(0, 16)}… · code ${(latest.code_commit || "").slice(0, 7)}` : "";
      const members = (latest.members || []).slice().sort((a, b) => a.rank - b.rank);
      const entered = new Set((latest.changes && latest.changes.entered) || []);
      if (members.length) {
        $("#members-wrap").hidden = false; $("#building").hidden = true;
        donut(members);
        let h = `<thead><tr>${t.mcols.map((c, i) => `<th class="${i > 4 ? "hidemob" : ""}">${c}</th>`).join("")}</tr></thead><tbody>`;
        members.forEach((m, i) => {
          const mt = m.metrics || {}, w = (m.weight_bps || 0) / 100;
          const prev = m.prev_rank;
          const delta = entered.has(m.mint) ? `<span class="tag ok">${t.newb}</span>` : prev ? (prev > m.rank ? `<span class="up">▲${prev - m.rank}</span>` : prev < m.rank ? `<span class="down">▼${m.rank - prev}</span>` : "•") : "•";
          h += `<tr><td class="rk" style="color:${COLORS[i % 10]}">${m.rank}</td><td class="tk"><b>${esc(m.ticker || "?")}</b><small>${short(m.mint)}</small></td><td><b>${w.toFixed(1)}%</b><span class="vbar" style="width:${w * 2}px"></span></td><td>${usd(mt.mc_usd)}</td><td>${usd(mt.liquidity_usd)}</td><td class="hidemob">${usd(mt.volume_usd)}</td><td class="hidemob">${delta}</td></tr>`;
        });
        $("#members").innerHTML = h + "</tbody>";
      } else {
        $("#members-wrap").hidden = true; $("#building").hidden = false;
        const ex = latest.excluded || [];
        $("#excl-summary").textContent = t.excl(ex.length, ex.filter((e) => e.reason === "insufficient_data").length);
      }
    }
    if (cands) {
      const list = (cands.candidates || []).filter((c) => (c.vol24h || 0) >= 1000 && (c.liq || 0) >= 1000 && (c.mc || 0) <= 200 * c.liq)
        .sort((a, b) => (b[sortKey] || 0) - (a[sortKey] || 0)).slice(0, 25);
      const maxv = Math.max(1, ...list.map((c) => c[sortKey] || 0));
      let h = `<thead><tr>${t.cols.map((c, i) => `<th class="${i === 2 || i === 4 ? "hidemob" : ""}">${c}</th>`).join("")}</tr></thead><tbody>`;
      if (!list.length) h += `<tr><td colspan="6" class="muted">${t.none}</td></tr>`;
      list.forEach((c, i) => {
        const st = c.status === "member" ? `<span class="tag ok">${t.member}</span>` : `<span class="tag f">${esc(REASON[c.status] || c.status || t.nodata)}</span>`;
        const v = (k) => k === sortKey ? `<b>${usd(c[k])}</b><span class="vbar" style="width:${Math.max(4, ((c[k] || 0) / maxv) * 60)}px"></span>` : usd(c[k]);
        h += `<tr><td class="rk">${i + 1}</td><td class="tk"><b>${esc(c.ticker || short(c.mint))}</b><small>${short(c.mint)}</small></td><td class="hidemob">${st}</td><td>${v("mc")}</td><td class="hidemob">${v("liq")}</td><td>${v("vol24h")}</td></tr>`;
      });
      $("#cands").innerHTML = h + "</tbody>";
    }
  }

  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".seg button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); sortKey = b.dataset.sort; render();
  }));

  async function load() {
    const get = (f) => fetch(DATA + f + "?t=" + Date.now()).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [l, c] = await Promise.all([get("latest.json"), get("candidates.json")]);
    if (l) latest = l; if (c) cands = c;
    if (!latest) { $("#building").hidden = false; }
    render();
  }
  load(); setInterval(load, 60000);
})();

// ---------- Chart & Buy + Check your rewards ----------
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
  const B58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  const isAddr = (s) => typeof s === "string" && B58.test(s);
  const ca = typeof CA === "string" && isAddr(CA) ? CA : null;
  const enc = (s) => encodeURIComponent(s);

  // Chart & Buy
  const VENUES = [
    { name: "pump.fun", url: (m) => `https://pump.fun/coin/${enc(m)}` },
    { name: "Jupiter", url: (m) => `https://jup.ag/swap/SOL-${enc(m)}` },
    { name: "Raydium", url: (m) => `https://raydium.io/swap/?inputMint=sol&outputMint=${enc(m)}` },
    { name: "DexScreener", url: (m) => `https://dexscreener.com/solana/${enc(m)}` },
  ];
  $("#venues").innerHTML = VENUES.map((v) => ca
    ? `<a class="venue" href="${v.url(ca)}" target="_blank" rel="noopener noreferrer"><b>${v.name}</b><span>Open ↗</span></a>`
    : `<button class="venue" type="button" disabled aria-disabled="true"><b>${v.name}</b><span>Available at launch</span></button>`).join("");
  if (ca) {
    $("#ca-text").textContent = ca;
    $("#chart-body").innerHTML = `<iframe title="GTASP10 chart" loading="lazy" src="https://dexscreener.com/solana/${enc(ca)}?embed=1&theme=dark&trades=0&info=0"></iframe>`;
    $("#chart-panel").classList.add("live");
    document.querySelector(".chart-note").remove();
  }

  // Rewards
  const SUPPLY_MIN = 1e-6; // 1 / 1,000,000 of supply
  const CURVE = [[0,0],[1,0],[1,1],[1.5,1],[1.75,1.5],[2,2],[2.5,3],[3,4],[4,5]];
  function multiplier(h) {
    if (h < 1) return 0;
    if (h >= 4) return 5;
    for (let i = 1; i < CURVE.length; i++) {
      const [h0, m0] = CURVE[i - 1], [h1, m1] = CURVE[i];
      if (h >= h0 && h < h1) return h1 === h0 ? m1 : m0 + ((m1 - m0) * (h - h0)) / (h1 - h0);
    }
    return 5;
  }
  const fmtHold = (sec) => { const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60); return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`; };
  const fmtPct = (x, d = 4) => (x * 100).toLocaleString("en-US", { maximumFractionDigits: d }) + "%";

  const EXAMPLE = {
    address: "7xKX…9fQa", holding_seconds: 9300, supply_share: 0.00042, draw_odds: 0.0031,
    accrued: [
      { ticker: "Basket token #1", amount: 1520.4, usd: 4.12 },
      { ticker: "Basket token #2", amount: 88210, usd: 2.87 },
      { ticker: "Basket token #3", amount: 312.9, usd: 1.05 },
    ],
  };

  function show(d, example) {
    const hours = (d.holding_seconds || 0) / 3600;
    const mult = typeof d.multiplier === "number" ? d.multiplier : multiplier(hours);
    const share = d.supply_share || 0;
    const eligible = typeof d.eligible === "boolean" ? d.eligible : share >= SUPPLY_MIN && hours >= 1;
    $("#rw-badge").textContent = example ? "Example" : "Live";
    $("#rw-badge").classList.toggle("live", !example);
    $("#rw-who").textContent = example ? `${d.address} (demo wallet)` : `${d.address.slice(0, 4)}…${d.address.slice(-4)}`;
    $("#rw-hold").textContent = fmtHold(d.holding_seconds || 0);
    $("#rw-mult").textContent = mult.toFixed(mult % 1 ? 2 : 0) + "×";
    $("#rw-meter").style.width = (mult / 5) * 100 + "%";
    $("#rw-elig").textContent = eligible ? "Eligible" : hours < 1 && share >= SUPPLY_MIN ? "Warming up" : "Not eligible";
    $("#rw-elig").className = eligible ? "ok" : "no";
    $("#rw-share").textContent = `holds ${fmtPct(share)} of supply · min 0.0001%`;
    $("#rw-odds").textContent = fmtPct(d.draw_odds || 0, 3);
    const list = d.accrued || [];
    $("#rw-list").innerHTML = list.length
      ? list.map((r) => `<div class="rw-row"><span>${esc(r.ticker)}</span><span class="mono">${Number(r.amount).toLocaleString("en-US", { maximumFractionDigits: 4 })}</span><span class="muted">${r.usd != null ? "≈ $" + Number(r.usd).toFixed(2) : ""}</span></div>`).join("")
      : `<p class="muted small">No basket rewards accrued yet.</p>`;
    $("#rw-foot").textContent = example
      ? "Example values for illustration only. Rewards depend on fees actually generated and are not guaranteed."
      : `Read-only data${d.as_of ? " as of " + new Date(d.as_of).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : ""}. Rewards depend on fees actually generated and are not guaranteed.`;
    $("#rw-result").classList.toggle("is-example", example);
  }
  show(EXAMPLE, true);

  const msg = (text, kind) => { const el = $("#rw-msg"); el.textContent = text; el.className = "rw-msg " + (kind || ""); };
  $("#rw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const addr = $("#rw-addr").value.trim();
    if (!isAddr(addr)) {
      msg(/\s/.test(addr) && addr.split(/\s+/).length >= 12
        ? "That looks like a seed phrase. Never share it with anyone. Paste only your public wallet address."
        : "That doesn't look like a Solana address (base58, 32–44 characters).", "err");
      return;
    }
    if (!ca) {
      msg("Valid address. Rewards tracking starts at launch, so here's an example of what you'll see.", "info");
      show(EXAMPLE, true);
      return;
    }
    msg("Loading…", "info");
    try {
      const r = await fetch(`data/wallets/${enc(addr)}.json?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { msg("No GTASP10 holdings found for this address yet.", "info"); return; }
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      d.address = addr;
      msg("", ""); show(d, false);
    } catch (_) {
      msg("Couldn't load rewards right now. Please try again in a minute.", "err");
    }
  });
})();
