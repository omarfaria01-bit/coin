(() => {
  "use strict";
  const root = document.getElementById("bt-root");
  if (!root) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const num = (v, d = 2) => (v == null || !isFinite(+v) ? "—" : (+v).toLocaleString("en-US", {
    maximumFractionDigits: d, minimumFractionDigits: d,
  }));
  const pct = (v) => (v == null || !isFinite(+v) ? "—" : (v * 100).toFixed(1) + "%");

  function seriesPath(points, key, xOf, yOf) {
    let d = "";
    let pen = false;
    points.forEach((p) => {
      const v = p[key];
      if (v == null || !(v > 0)) { pen = false; return; }
      d += (pen ? "L" : "M") + xOf(p.t) + " " + yOf(v);
      pen = true;
    });
    return d;
  }

  function draw(data) {
    const svg = document.getElementById("bt-chart");
    const points = (data.curve || []).filter((p) => p && p.t && isFinite(+p.index));
    if (!svg || points.length < 2) {
      if (svg) svg.innerHTML = "";
      return;
    }
    const keys = ["index", "equal_weight", "top_coin", "sol"].filter((k) => points.some((p) => p[k] > 0));
    const vals = [];
    points.forEach((p) => keys.forEach((k) => { if (p[k] > 0) vals.push(+p[k]); }));
    const minV = Math.min(...vals);
    const maxV = Math.max(...vals);
    const W = 720, H = 280, L = 52, R = 12, T = 12, B = 28;
    const t0 = Date.parse(points[0].t);
    const t1 = Date.parse(points[points.length - 1].t) || t0 + 1;
    const xOf = (t) => {
      const x = (Date.parse(t) - t0) / (t1 - t0 || 1);
      return L + Math.min(1, Math.max(0, x)) * (W - L - R);
    };
    const yOf = (v) => {
      const lo = Math.log(minV), hi = Math.log(maxV);
      const span = hi - lo || 1;
      const y = (Math.log(v) - lo) / span;
      return H - B - y * (H - T - B);
    };
    const colors = { index: "#ff2d95", equal_weight: "#22e3ff", top_coin: "#ffd166", sol: "#c4b5fd" };
    let body = `<rect width="${W}" height="${H}" fill="#07010f" rx="12"/>`;
    for (let i = 0; i < 4; i++) {
      const v = Math.exp(Math.log(minV) + (Math.log(maxV) - Math.log(minV)) * (i / 3));
      const y = yOf(v);
      body += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#ffffff14"/>`;
      body += `<text x="${L - 6}" y="${y + 4}" text-anchor="end" fill="#b9a6d3" font-size="11">${v >= 10 ? v.toFixed(0) : v.toFixed(2)}</text>`;
    }
    body += `<text x="${L}" y="${H - 8}" fill="#b9a6d3" font-size="11">${esc(points[0].t.slice(0, 10))}</text>`;
    body += `<text x="${W - R}" y="${H - 8}" text-anchor="end" fill="#b9a6d3" font-size="11">${esc(points[points.length - 1].t.slice(0, 10))}</text>`;
    keys.forEach((k) => {
      body += `<path d="${seriesPath(points, k, xOf, yOf)}" fill="none" stroke="${colors[k]}" stroke-width="${k === "index" ? 2.6 : 1.6}" stroke-linejoin="round" stroke-linecap="round"/>`;
    });
    svg.innerHTML = body;
    const names = { index: "Index", equal_weight: "Equal weight", top_coin: "Largest coin", sol: "SOL" };
    const legend = document.getElementById("bt-legend");
    if (legend) {
      legend.innerHTML = keys.map((k) => `<span><i style="background:${colors[k]}"></i>${names[k]}</span>`).join("");
    }
  }

  function fill(data) {
    const hist = data.history || {};
    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    set("bt-window", hist.start && hist.end ? `${hist.start.slice(0, 13)}Z → ${hist.end.slice(0, 13)}Z` : "—");
    set("bt-hours", hist.hours != null ? String(hist.hours) + " hours" : "—");
    set("bt-rebalances", hist.rebalances != null ? String(hist.rebalances) : "—");
    set("bt-index", num(data.index && data.index.end, 2));
    set("bt-dd", pct(data.index && data.index.max_drawdown));
    set("bt-equal", num(data.equal_weight && data.equal_weight.end, 2));
    set("bt-top", num(data.top_coin && data.top_coin.end, 2));
    set("bt-sol", num(data.sol && data.sol.end, 2));
    const top = data.top_coin || {};
    set("bt-top-name", top.ticker ? `Largest coin at the anchor (${top.ticker}), bought and held` : "Largest coin");
    const pub = data.published_replay || {};
    const pubEl = document.getElementById("bt-published");
    if (pubEl) {
      pubEl.textContent = pub.index_end != null
        ? `Official hourly files only, full filters re-checked: ${pub.hours_with_members || pub.hours || 0} hours with a basket, ${pub.rebalances || 0} steps, simulated value ${num(pub.index_end, 3)} (start 1). ${pub.note || ""}`
        : "";
    }
    const coins = document.getElementById("bt-coins");
    if (coins) {
      coins.innerHTML = (data.coins || []).map((c) => `<span>${esc(c.ticker || "—")} · ${esc(c.hours)}h</span>`).join("");
    }
    const list = document.getElementById("bt-caveats");
    if (list) {
      list.innerHTML = (data.caveats || []).map((c) => `<li>${esc(c)}</li>`).join("");
    }
    draw(data);
  }

  fetch("data/backtest.json", { cache: "no-store" })
    .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
    .then(fill)
    .catch(() => {
      const el = document.getElementById("bt-status");
      if (el) el.textContent = "The backtest file is not available right now.";
    });
})();
