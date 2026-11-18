(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const DATA = "data/";
  const RELEASE = new Date(2026, 10, 19, 0, 0, 0); // 19 Nov 2026 00:00 local time
  let lang = localStorage.getItem("gtasp10_lang") || "it";
  let latest = null, cands = null, sortKey = "vol24h";

  const EN = {
    nav_index:"Index", nav_how:"How it works", nav_rules:"Rules",
    kicker:"On-chain index · Solana · GTA 6 narrative",
    sub:"The 10 best GTA 6 memecoins on Solana, in a single coin. Recalculated every hour by a public formula. 100% of creator fees go back to holders.",
    cd_release:"GTA 6 release", cd_hour:"Next draw and rebalance", ca:"Contract address", soon:"Coming soon",
    draft:"Draft · temporary name and ticker · live dry-run data",
    idx_title:"Live index", coins:"coins", building:"Top 10 under construction",
    building_p:"The index samples every coin every 5 minutes. As soon as coins pass every filter, they enter the top 10.",
    next_update:"Next update in", cand_title:"Tracked GTA candidates",
    cand_warn:"Preview: these are candidates, NOT index members. Not a buy recommendation.",
    by_vol:"24h volume", by_mc:"Market cap", by_liq:"Liquidity",
    cand_note:"Showing candidates with at least $1,000 of 24h volume. Status = first filter failed in the latest hourly run.",
    how_title:"How it works", fees_t:"100% of fees go back",
    fees_a:"Holder rewards, paid in the basket tokens (not in GTASP10)", fees_b:"Hourly draw prize pot",
    fees_n:"No team share. No buyback.", draw_t:"A draw every hour",
    draw_1:"Odds proportional to the square root of your holder score", draw_2:"Linked wallets grouped, capped at 5%",
    draw_3:"Randomness verifiable on-chain", draw_4:"Pot too small? It rolls over to the next hour",
    elig_t:"Who takes part", elig_1:"Hold at least 1/1,000,000 of the supply", elig_2:"Nothing accrues in the first hour of holding",
    elig_3:"The longer you hold, the higher the multiplier, up to 5× after 4 hours", elig_4:"Public dev wallet, payouts reproducible from on-chain data",
    curve_t:"Holding multiplier", rules_t:"Rules and transparency", rules_s:"Public formula, recalculated every hour over the previous 24 hours.",
    r_universe:"1 · Universe", r_universe_p:"Every Solana coin with a GTA reference in its name, ticker or description: GTA, GTA 6, Grand Theft Auto, Vice City, Leonida, Lucia, Jason Duval, Rockstar, Vercetti and a broad series vocabulary. Manual exclusions only for scams.",
    r_filters:"2 · Filters (all required)", f1:"Age ≥ 4h", f2:"Liquidity ≥ $50k", f3:"Top 10 holders 13–27%", f4:"Fees ≥ 8 SOL", f5:"Launch bundle ≤ 30%", f7:"Creator ≤ 3 tokens in 7 days", f8:"Authorities revoked", f9:"200+ traders", f10:"Volume > 0", f11:"Market cap ≤ 100× liquidity",
    r_score:"3 · Score", r_score_p:"Log scale: one huge coin can't crush the others.",
    r_member:"4 · Entry and exit", r_member_p:"A new coin enters if it reaches the top 8. A member exits if it falls below 12th or fails a filter (immediately). Emergency removal if liquidity drops 50% within an hour or authorities are re-enabled.",
    r_weights:"5 · Weights", r_weights_p:"50% market-cap share + 50% volume share, capped at 25% per coin. With fewer than 4 members weights are equal.",
    r_verify:"6 · Verifiable", r_verify_p:"Every hourly result publishes the hash of its parameters and inputs: anyone can recompute the index.",
    q1:"What is GTASP10?", a1:"An index coin on Solana that tracks the 10 best memecoins of the GTA 6 narrative, picked every hour by public rules.",
    q2:"How do I receive rewards?", a2:"By holding at least 1/1,000,000 of the supply. 70% of creator fees is distributed to holders in the basket tokens, based on score and holding multiplier.",
    q3:"How does the draw work?", a3:"Every hour 30% of fees goes into a prize pot. Odds grow with the square root of the score, linked wallets are grouped with a 5% cap and randomness is verifiable. If the pot is too small it rolls over to the next hour.",
    q4:"Why is the top 10 empty?", a4:"The filters are strict and each coin's data is still being collected. Coins enter only when they pass all of them.",
    q5:"Where is the contract address?", a5:"Not published yet. Distrust anyone sharing one before the official announcement.",
    q6:"Does the team keep part of the fees?", a6:"No. 100% of creator fees go back to the community: 70% rewards, 30% draw. No buyback.",
    disc:"This site is an informational draft. It is not financial advice. No returns are promised or guaranteed: memecoins are extremely volatile and you can lose everything. GTASP10 is not affiliated with Rockstar Games or Take-Two Interactive. Grand Theft Auto and GTA are trademarks of their respective owners."
  };
  const T = {
    it:{asof:"Ultimo calcolo", days:"g", none:"Nessuna candidata con dati sufficienti", member:"membro", nodata:"dati in raccolta",
        cols:["#","Coin","Stato","Market cap","Liquidità","Vol 24h"], mcols:["#","Coin","Peso","Market cap","Liquidità","Volume","Δ"],
        excl:(n,r)=>`${n} candidate valutate, ${r} in attesa di dati`, out:"GTA 6 è uscito!", newb:"nuova"},
    en:{asof:"Last run", days:"d", none:"No candidate with enough data", member:"member", nodata:"collecting data",
        cols:["#","Coin","Status","Market cap","Liquidity","Vol 24h"], mcols:["#","Coin","Weight","Market cap","Liquidity","Volume","Δ"],
        excl:(n,r)=>`${n} candidates evaluated, ${r} waiting for data`, out:"GTA 6 is out!", newb:"new"}
  };
  const REASON = {
    it:{insufficient_data:"dati in raccolta",F1:"troppo giovane",F2:"liquidità < $50k",F3:"top holder fuori 13–27%",F4:"fee < 8 SOL",F5:"bundle > 30%",F7:"creator seriale",F8:"authority attive",F8c:"programma token",F9:"< 200 trader",F10:"volume 0",F11:"MC > 100× liq",deny:"escluso (scam)"},
    en:{insufficient_data:"collecting data",F1:"too young",F2:"liquidity < $50k",F3:"top holders outside 13–27%",F4:"fees < 8 SOL",F5:"bundle > 30%",F7:"serial creator",F8:"authorities active",F8c:"token program",F9:"< 200 traders",F10:"zero volume",F11:"MC > 100× liq",deny:"excluded (scam)"}
  };

  // i18n
  const itText = {};
  document.querySelectorAll("[data-i18n]").forEach((el) => (itText[el.dataset.i18n] = el.innerHTML));
  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const k = el.dataset.i18n;
      el.innerHTML = lang === "en" && EN[k] ? EN[k] : itText[k];
    });
    $("#lang").textContent = lang === "it" ? "EN" : "IT";
    render();
  }
  $("#lang").addEventListener("click", () => { lang = lang === "it" ? "en" : "it"; localStorage.setItem("gtasp10_lang", lang); applyLang(); });

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
    if (d <= 0) $("#cd-release").textContent = T[lang].out;
    else {
      const days = Math.floor(d / 864e5); d -= days * 864e5;
      const h = Math.floor(d / 36e5); d -= h * 36e5;
      const m = Math.floor(d / 6e4); const s = Math.floor((d - m * 6e4) / 1e3);
      $("#cd-release").textContent = (days ? days + T[lang].days + " " : "") + `${pad(h)}:${pad(m)}:${pad(s)}`;
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
    const t = T[lang];
    if (latest) {
      const asof = latest.as_of ? new Date(latest.as_of) : null;
      $("#asof").textContent = asof ? `${t.asof}: ${asof.toLocaleString(lang === "it" ? "it-IT" : "en-GB", { dateStyle: "medium", timeStyle: "short" })}${latest.dry_run ? " · dry-run" : ""}` : "";
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
      const list = (cands.candidates || []).filter((c) => (c.vol24h || 0) >= 1000)
        .sort((a, b) => (b[sortKey] || 0) - (a[sortKey] || 0)).slice(0, 25);
      const maxv = Math.max(1, ...list.map((c) => c[sortKey] || 0));
      let h = `<thead><tr>${t.cols.map((c, i) => `<th class="${i === 2 || i === 4 ? "hidemob" : ""}">${c}</th>`).join("")}</tr></thead><tbody>`;
      if (!list.length) h += `<tr><td colspan="6" class="muted">${t.none}</td></tr>`;
      list.forEach((c, i) => {
        const st = c.status === "member" ? `<span class="tag ok">${t.member}</span>` : `<span class="tag f">${esc(REASON[lang][c.status] || c.status || t.nodata)}</span>`;
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
  applyLang();
})();
