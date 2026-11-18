(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const DATA = "data/";
  const RELEASE = new Date(2026, 10, 19, 0, 0, 0); // 19 Nov 2026 00:00 local time
  let lang = localStorage.getItem("gtasp10_lang") || "en";
  let latest = null, cands = null, sortKey = "vol24h";

  const IT = {
"nav_index": "Indice",
"nav_how": "Come funziona",
"nav_rules": "Regole",
"kicker": "Indice on-chain · Solana · Narrativa GTA 6",
"sub": "Le 10 migliori memecoin GTA 6 su Solana, in un'unica coin. Ricalcolato ogni ora con una formula pubblica. Il 100% delle fee del creator torna agli holder.",
"cd_release": "Uscita GTA 6",
"cd_hour": "Prossima estrazione e ribilanciamento",
"ca": "Contract address",
"soon": "Coming soon",
"draft": "Bozza · nome e ticker temporanei · dati live in dry-run",
"idx_title": "Indice live",
"coins": "coin",
"building": "Top 10 in costruzione",
"building_p": "L'indice raccoglie i dati di ogni coin ogni 5 minuti. Appena le coin superano tutti i filtri, entrano nella top 10.",
"next_update": "Prossimo aggiornamento tra",
"cand_title": "Candidate GTA monitorate",
"cand_warn": "Anteprima: queste sono candidate, NON membri dell'indice. Nessun consiglio di acquisto.",
"by_vol": "Volume 24h",
"by_mc": "Market cap",
"by_liq": "Liquidità",
"cand_note": "Mostrate le candidate con almeno 1.000 $ di volume 24h e un market cap realistico rispetto alla liquidità. Stato = primo filtro non superato nell'ultimo calcolo orario.",
"how_title": "Come funziona",
"fees_t": "100% delle fee torna indietro",
"fees_a": "Reward agli holder, pagati nei token del paniere (non in GTASP10)",
"fees_b": "Montepremi dell'estrazione oraria",
"fees_n": "Nessuna quota al team. Nessun buyback.",
"draw_t": "Estrazione ogni ora",
"draw_1": "Probabilità proporzionale alla radice quadrata del tuo punteggio holder",
"draw_2": "Wallet collegati raggruppati, con un tetto del 5%",
"draw_3": "Casualità verificabile on-chain",
"draw_4": "Montepremi troppo piccolo? Passa all'ora successiva",
"elig_t": "Chi partecipa",
"elig_1": "Basta tenere almeno 1/1.000.000 della supply",
"elig_2": "Nella prima ora di holding non si matura nulla",
"elig_3": "Più tieni, più cresce il moltiplicatore, fino a 5× dopo 4 ore",
"elig_4": "Wallet del dev pubblico, pagamenti riproducibili dai dati on-chain",
"curve_t": "Moltiplicatore di holding",
"rules_t": "Regole e trasparenza",
"rules_s": "Formula pubblica, ricalcolata ogni ora sulle 24 ore precedenti.",
"r_universe": "1 · Universo",
"r_universe_p": "Ogni coin Solana con un riferimento a GTA nel nome, nel ticker o nella descrizione: GTA, GTA 6, Grand Theft Auto, Vice City, Leonida, Lucia, Jason Duval, Rockstar, Vercetti e un ampio vocabolario della serie. Esclusioni manuali solo per le truffe.",
"r_filters": "2 · Filtri (tutti obbligatori)",
"f1": "Età ≥ 4h",
"f2": "Liquidità ≥ $50k",
"f3": "Top 10 holder 13–27%",
"f4": "Fee ≥ 8 SOL",
"f5": "Bundle al lancio ≤ 30%",
"f7": "Creator ≤ 3 token in 7 giorni",
"f8": "Authority revocate",
"f9": "200+ trader",
"f10": "Volume &gt; 0",
"f11": "Market cap ≤ 100× liquidità",
"r_score": "3 · Punteggio",
"r_score_p": "Scala logaritmica: una coin enorme non schiaccia le altre.",
"r_member": "4 · Entrata e uscita",
"r_member_p": "Una nuova coin entra se arriva tra le prime 8. Un membro esce se scende sotto il 12° posto o se fallisce un filtro (subito). Rimozione d'emergenza se la liquidità crolla del 50% in un'ora o le authority vengono riattivate.",
"r_weights": "5 · Pesi",
"r_weights_p": "50% quota di market cap + 50% quota di volume, con un massimo del 25% per coin. Con meno di 4 membri i pesi sono uguali.",
"r_verify": "6 · Verificabile",
"r_verify_p": "Ogni risultato orario pubblica l'hash dei parametri e degli input: chiunque può ricalcolare l'indice.",
"q1": "Cos'è GTASP10?",
"a1": "Una coin indice su Solana che segue le 10 migliori memecoin della narrativa GTA 6, scelte ogni ora da regole pubbliche.",
"q2": "Come ricevo i reward?",
"a2": "Tenendo almeno 1/1.000.000 della supply. Il 70% delle fee del creator viene distribuito agli holder nei token del paniere, in base al punteggio e al moltiplicatore di holding.",
"q3": "Come funziona l'estrazione?",
"a3": "Ogni ora il 30% delle fee va in un montepremi. Le probabilità crescono con la radice quadrata del punteggio, i wallet collegati sono raggruppati con un tetto del 5% e la casualità è verificabile. Se il montepremi è troppo piccolo passa all'ora dopo.",
"q4": "Perché la top 10 è vuota?",
"a4": "I filtri sono severi e i dati di ogni coin si stanno ancora raccogliendo. Le coin entrano solo quando li superano tutti.",
"q5": "Dov'è il contract address?",
"a5": "Non ancora pubblicato. Diffida di chiunque ne diffonda uno prima dell'annuncio ufficiale.",
"q6": "Il team tiene una parte delle fee?",
"a6": "No. Il 100% delle fee del creator torna alla community: 70% reward, 30% estrazione. Nessun buyback.",
"disc": "Questo sito è una bozza a scopo informativo. Non è un consiglio finanziario. Nessun rendimento è promesso o garantito: le memecoin sono estremamente volatili e puoi perdere tutto. GTASP10 non è affiliato con Rockstar Games o Take-Two Interactive. Grand Theft Auto e GTA sono marchi dei rispettivi proprietari."
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
  const TITLE_EN = document.title;
  const enText = {};
  document.querySelectorAll("[data-i18n]").forEach((el) => (enText[el.dataset.i18n] = el.innerHTML));
  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const k = el.dataset.i18n;
      el.innerHTML = lang === "it" && IT[k] ? IT[k] : enText[k];
    });
    $("#lang").textContent = lang === "en" ? "IT" : "EN";
    document.title = lang === "it" ? "GTASP10 — Le top 10 memecoin GTA 6 su Solana in un indice" : TITLE_EN;
    render();
  }
  $("#lang").addEventListener("click", () => { lang = lang === "en" ? "it" : "en"; localStorage.setItem("gtasp10_lang", lang); applyLang(); });

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
      const list = (cands.candidates || []).filter((c) => (c.vol24h || 0) >= 1000 && (c.liq || 0) >= 1000 && (c.mc || 0) <= 200 * c.liq)
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
