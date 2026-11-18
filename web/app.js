(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const DATA = "data/";
<<<<<<< HEAD
  // GTA 6: 19 Nov 2026 00:00 America/New_York (EST, UTC-5) = 2026-11-19T05:00:00Z
  const RELEASE = new Date("2026-11-19T05:00:00.000Z");
  const MIN_LIQ = 10000;
  const DEX_IMG = (m) => "https://dd.dexscreener.com/ds-data/tokens/solana/" + m + ".png";
  const DEX_URL = (m) => "https://dexscreener.com/solana/" + encodeURIComponent(m);
  // Same static fallback pool used by /usr/local/bin/gtasp10-logo.py
  const STATIC_TOP = [
    "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz",
    "nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump",
    "DKYcjobF7HPtL9RyQBRdeRQ2iWvizpfbgWwPWNXdpump",
    "AKotzk1dhcNangAJBtvNKtT9bhbSVZc2mMhRFgkFpump",
    "7KBFymfGAe8MmKEuNersoM59TvpiHzZ76jP7rSLrpump",
    "HsZXb9rppRQarZHHCvuLkKP7sAKPMCwrarf5KTTcpump",
    "HZbiEpF2oM658EpjNRRqxharz5L9Ddm8akpSH2R5pump",
    "BsbsB3WLq7vbY5En3MBCAsTrcwaCxNKY2Mp5pGuLpump",
    "HCNhQCu5nrmWhSE3mo7fRU9eGiGLmi2fnE8omgLpump",
    "9HFUEab7sompLDPTAaTGkryMNGbtBaFMhHMVpJEBpump",
  ];
  let latest = null, cands = null, logoMeta = null, sortKey = "vol24h";
  const dexCache = {};

  const t = {asof:"Last run", days:"d", none:"No candidate with enough data", member:"member", nodata:"collecting data",
        cols:["#","Coin","Status","Market cap","Liquidity","Vol 24h"],
=======
  const RELEASE = new Date(2026, 10, 19, 0, 0, 0); // 19 Nov 2026 00:00 local time
  let latest = null, cands = null, sortKey = "vol24h";


  const t = {asof:"Last run", days:"d", none:"No candidate with enough data", member:"member", nodata:"collecting data",
        cols:["#","Coin","Status","Market cap","Liquidity","Vol 24h"], mcols:["#","Coin","Weight","Market cap","Liquidity","Volume","Δ"],
>>>>>>> origin/main
        excl:(n,r)=>`${n} candidates evaluated, ${r} waiting for data`, out:"GTA 6 is out!", newb:"new"};

  const REASON = {insufficient_data:"collecting data",F1:"too young",F2:"liquidity < $50k",F3:"top holders outside 13–27%",F4:"fees < 8 SOL",F5:"bundle > 30%",F7:"serial creator",F8:"authorities active",F8c:"token program",F9:"< 200 traders",F10:"zero volume",F11:"MC > 100× liq",deny:"excluded (scam)"};


<<<<<<< HEAD
=======
  // i18n


>>>>>>> origin/main
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
<<<<<<< HEAD
  const pct = (v) => {
    if (v == null || !isFinite(+v)) return "—";
    const n = +v;
    const sign = n > 0 ? "+" : "";
    return sign + n.toFixed(Math.abs(n) >= 10 ? 1 : 2) + "%";
  };

  // countdowns — RELEASE is a fixed UTC instant, identical for every visitor
=======

  // countdowns
>>>>>>> origin/main
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
<<<<<<< HEAD
    const total = members.reduce((a, m) => a + (m.weight || 0), 0) || 1;
    const r = 80, c = 2 * Math.PI * r; let off = 0, s = "";
    members.forEach((m, i) => {
      const f = (m.weight || 0) / total;
=======
    const total = members.reduce((a, m) => a + (m.weight_bps || 0), 0) || 1;
    const r = 80, c = 2 * Math.PI * r; let off = 0, s = "";
    members.forEach((m, i) => {
      const f = (m.weight_bps || 0) / total;
>>>>>>> origin/main
      s += `<circle cx="110" cy="110" r="${r}" fill="none" stroke="${COLORS[i % 10]}" stroke-width="30" stroke-dasharray="${f * c} ${c}" stroke-dashoffset="${-off * c}" transform="rotate(-90 110 110)"><title>${esc(m.ticker)} ${(f * 100).toFixed(1)}%</title></circle>`;
      off += f;
    });
    $("#donut").innerHTML = s; $("#donut-n").textContent = members.length;
  }

<<<<<<< HEAD
  function capWeights(rows) {
    const n = rows.length;
    if (!n) return rows;
    if (n < 4) {
      const w = 100 / n;
      rows.forEach((r) => { r.weight = w; });
      return rows;
    }
    const mcSum = rows.reduce((a, r) => a + (r.mc || 0), 0) || 1;
    const volSum = rows.reduce((a, r) => a + (r.vol24h || 0), 0) || 1;
    let raw = rows.map((r) => 0.5 * ((r.mc || 0) / mcSum) + 0.5 * ((r.vol24h || 0) / volSum));
    const CAP = 0.25;
    for (let pass = 0; pass < 10; pass++) {
      let excess = 0, free = 0;
      raw = raw.map((w) => {
        if (w > CAP) { excess += w - CAP; return CAP; }
        free += w;
        return w;
      });
      if (excess < 1e-12) break;
      if (free <= 0) break;
      raw = raw.map((w) => (w < CAP ? w + excess * (w / free) : w));
    }
    const sum = raw.reduce((a, b) => a + b, 0) || 1;
    rows.forEach((r, i) => { r.weight = (raw[i] / sum) * 100; });
    return rows;
  }

  function mergeRow(base) {
    const d = dexCache[base.mint] || {};
    return {
      ...base,
      name: base.name || d.name || base.ticker || short(base.mint),
      ticker: base.ticker || d.ticker || "?",
      mc: d.mc || base.mc,
      liq: d.liq || base.liq,
      vol24h: d.vol24h ?? base.vol24h,
      chg24h: d.chg24h ?? base.chg24h,
      image: d.image || base.image || DEX_IMG(base.mint),
    };
  }

  function officialRows() {
    const members = ((latest && latest.members) || []).slice().sort((a, b) => a.rank - b.rank);
    if (!members.length) return [];
    const entered = new Set((latest.changes && latest.changes.entered) || []);
    return members.map((m, i) => {
      const mt = m.metrics || {};
      return mergeRow({
        official: true,
        rank: m.rank || i + 1,
        mint: m.mint,
        ticker: m.ticker || mt.ticker,
        name: mt.name,
        weight: (m.weight_bps || 0) / 100,
        mc: mt.mc_usd,
        liq: mt.liquidity_usd,
        vol24h: mt.volume_usd,
        prev: m.prev_rank,
        isNew: entered.has(m.mint),
      });
    });
  }

  function previewPoolMints() {
    const fromLogo = ((logoMeta && logoMeta.coins) || []).map((c) => c.mint).filter(Boolean);
    const have = new Set(fromLogo);
    const sane = ((cands && cands.candidates) || []).filter((c) =>
      (c.mc || 0) >= 50000 && (c.liq || 0) >= MIN_LIQ && (c.vol24h || 0) >= 5000 && (c.liq || 0) <= (c.mc || 0)
    ).sort((a, b) => (b.mc || 0) - (a.mc || 0));
    const extra = [];
    for (const c of sane) {
      if (!have.has(c.mint)) { extra.push(c.mint); have.add(c.mint); }
    }
    for (const m of STATIC_TOP) {
      if (!have.has(m)) { extra.push(m); have.add(m); }
    }
    return fromLogo.concat(extra).slice(0, 30);
  }

  function previewRows() {
    const byMint = {};
    ((cands && cands.candidates) || []).forEach((c) => { byMint[c.mint] = c; });
    ((logoMeta && logoMeta.coins) || []).forEach((c) => {
      byMint[c.mint] = { ...(byMint[c.mint] || {}), mint: c.mint, ticker: c.ticker || (byMint[c.mint] || {}).ticker, mc: (byMint[c.mint] || {}).mc || c.mcap_usd };
    });
    const pool = previewPoolMints();
    let rows = pool.map((mint, i) => {
      const c = byMint[mint] || { mint };
      return mergeRow({
        official: false,
        rank: i + 1,
        mint,
        ticker: c.ticker,
        mc: c.mc,
        liq: c.liq,
        vol24h: c.vol24h,
      });
    });
    // Prefer DexScreener market cap when present (same rule as the logo fallback)
    rows = rows.filter((r) => (r.liq == null || r.liq >= MIN_LIQ) && (r.mc || 0) > 0);
    rows.sort((a, b) => (b.mc || 0) - (a.mc || 0));
    rows = rows.slice(0, 10).map((r, i) => ({ ...r, rank: i + 1 }));
    return capWeights(rows);
  }

  // CSP (no inline handlers): a broken coin logo falls back to its initials.
  document.addEventListener("error", (e) => {
    const el = e.target;
    if (el && el.classList && el.classList.contains("coin-logo")) el.parentNode.classList.add("noimg");
  }, true);

  function coinCell(r) {
    const initial = esc((r.ticker || "?").slice(0, 3).toUpperCase());
    const name = esc(r.name || r.ticker || "?");
    const ticker = esc(r.ticker || "?");
    const img = esc(r.image || DEX_IMG(r.mint));
    return `<div class="coin"><img class="coin-logo" src="${img}" alt="" width="36" height="36" loading="lazy" referrerpolicy="no-referrer"><span class="coin-fb" aria-hidden="true">${initial}</span><span class="coin-meta"><b>${name}</b><small>${ticker}</small></span></div>`;
  }

  function chgCell(v) {
    if (v == null || !isFinite(+v)) return `<span class="chg">—</span>`;
    const cls = +v > 0 ? "up" : +v < 0 ? "down" : "";
    return `<span class="chg ${cls}">${pct(v)}</span>`;
  }

  function renderBoard(rows, official) {
    const wrap = $("#members-wrap");
    const grid = wrap.querySelector(".members-grid");
    const banner = $("#board-banner");
    wrap.hidden = false;
    banner.hidden = official;
    grid.classList.toggle("preview", !official);
    $("#building").hidden = true;
    if (official) donut(rows);

    const head = ["#","Coin","Weight","Market cap","Liquidity","24h volume","24h","Chart"];
    let table = `<div class="board-tbl-wrap"><table class="board-tbl"><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
    let cards = `<div class="board-cards">`;
    rows.forEach((r, i) => {
      const color = COLORS[i % 10];
      const w = r.weight != null && isFinite(r.weight) ? r.weight.toFixed(1) + "%" : "—";
      const bar = r.weight != null ? `<span class="vbar" style="width:${Math.max(4, r.weight * 1.6)}px"></span>` : "";
      const href = DEX_URL(r.mint);
      table += `<tr>
        <td class="rk" style="color:${color}">#${r.rank}</td>
        <td>${coinCell(r)}</td>
        <td><span class="wcell"><b>${w}</b>${bar}</span></td>
        <td>${usd(r.mc)}</td>
        <td>${usd(r.liq)}</td>
        <td>${usd(r.vol24h)}</td>
        <td>${chgCell(r.chg24h)}</td>
        <td><a class="dex-link" href="${href}" target="_blank" rel="noopener noreferrer">Dex ↗</a></td>
      </tr>`;
      cards += `<a class="bcard" href="${href}" target="_blank" rel="noopener noreferrer">
        <div class="bcard-top"><span class="rk" style="color:${color}">#${r.rank}</span>${coinCell(r)}<span class="chg-wrap">${chgCell(r.chg24h)}</span></div>
        <div class="bcard-grid">
          <span><span class="k">${official ? "Index weight" : "Preview weight"}</span><span class="v">${w}</span></span>
          <span><span class="k">Market cap</span><span class="v">${usd(r.mc)}</span></span>
          <span><span class="k">Liquidity</span><span class="v">${usd(r.liq)}</span></span>
          <span><span class="k">24h volume</span><span class="v">${usd(r.vol24h)}</span></span>
        </div>
        <div class="bcard-foot"><span class="mono small muted">${short(r.mint)}</span><span class="dex-link">DexScreener ↗</span></div>
      </a>`;
    });
    table += "</tbody></table></div>";
    cards += "</div>";
    $("#board").innerHTML = table + cards;
  }

  function render() {
    if (!latest && !cands && !logoMeta) return;
=======
  function render() {
    if (!latest && !cands) return;
>>>>>>> origin/main
    if (latest) {
      const asof = latest.as_of ? new Date(latest.as_of) : null;
      $("#asof").textContent = asof ? `${t.asof}: ${asof.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}${latest.dry_run ? " · dry-run" : ""}` : "";
      $("#hashes").textContent = latest.params_hash ? `params ${latest.params_hash.slice(0, 16)}… · inputs ${(latest.inputs_hash || "").slice(0, 16)}… · code ${(latest.code_commit || "").slice(0, 7)}` : "";
<<<<<<< HEAD
    }
    const official = officialRows();
    if (official.length) {
      renderBoard(official, true);
    } else {
      const preview = previewRows();
      if (preview.length) {
        renderBoard(preview, false);
        const ex = (latest && latest.excluded) || [];
        if (ex.length) $("#asof").textContent = ($("#asof").textContent ? $("#asof").textContent + " · " : "") + t.excl(ex.length, ex.filter((e) => e.reason === "insufficient_data").length);
      } else {
        $("#members-wrap").hidden = true;
        $("#board-banner").hidden = true;
        $("#building").hidden = false;
        const ex = (latest && latest.excluded) || [];
=======
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
>>>>>>> origin/main
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

<<<<<<< HEAD
  async function enrichDex(mints) {
    const need = mints.filter((m) => !dexCache[m]);
    if (!need.length) return false;
    let changed = false;
    for (let i = 0; i < need.length; i += 30) {
      const chunk = need.slice(i, i + 30);
      try {
        const r = await fetch("https://api.dexscreener.com/tokens/v1/solana/" + chunk.join(","));
        if (!r.ok) continue;
        const data = await r.json();
        const list = Array.isArray(data) ? data : data.pairs || [];
        for (const p of list) {
          const m = (p.baseToken || {}).address;
          if (!m || !chunk.includes(m)) continue;
          const liq = +((p.liquidity || {}).usd || 0);
          const prev = dexCache[m];
          if (prev && prev.liq >= liq) continue;
          dexCache[m] = {
            name: (p.baseToken || {}).name,
            ticker: (p.baseToken || {}).symbol,
            liq,
            mc: +(p.marketCap || p.fdv || 0),
            vol24h: +((p.volume || {}).h24 || 0),
            chg24h: (p.priceChange || {}).h24,
            image: (p.info || {}).imageUrl || DEX_IMG(m),
          };
          changed = true;
        }
      } catch (_) { /* public API optional; table still renders from local JSON */ }
    }
    return changed;
  }

  async function load() {
    const get = (f) => fetch(f + "?t=" + Date.now()).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [l, c, logo] = await Promise.all([
      get(DATA + "latest.json"),
      get(DATA + "candidates.json"),
      get("logo.json"),
    ]);
    if (l) latest = l; if (c) cands = c; if (logo) logoMeta = logo;
    if (!latest && !cands && !logoMeta) { $("#building").hidden = false; }
    render();
    const official = officialRows();
    const mints = official.length ? official.map((r) => r.mint) : previewPoolMints();
    if (mints.length && await enrichDex(mints)) render();
=======
  async function load() {
    const get = (f) => fetch(DATA + f + "?t=" + Date.now()).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const [l, c] = await Promise.all([get("latest.json"), get("candidates.json")]);
    if (l) latest = l; if (c) cands = c;
    if (!latest) { $("#building").hidden = false; }
    render();
>>>>>>> origin/main
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
<<<<<<< HEAD
    const note = document.querySelector(".chart-note");
    if (note) note.remove();
=======
    document.querySelector(".chart-note").remove();
>>>>>>> origin/main
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
