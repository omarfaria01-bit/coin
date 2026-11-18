// Public rules in force (#345, D50), from data/fee-bot.json written by the fee bot. Text only, no HTML.
(() => {
  const box = document.getElementById("rules-lock");
  if (!box) return;
  fetch(`data/fee-bot.json?t=${Date.now()}`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      const e = d && d.econ;
      if (!e || !/^[0-9a-f]{64}$/.test(String(e.sha256))) return;
      box.textContent = "";
      const p = document.createElement("p");
      p.className = "small";
      p.append("Rules in force: sha256 ");
      const h = document.createElement("span");
      h.className = "mono";
      h.textContent = `${e.sha256.slice(0, 16)}…`;
      h.title = e.sha256;
      p.append(h, `, since ${String(e.effective_from).slice(0, 10)}.`);
      box.append(p);
      for (const u of Array.isArray(e.upcoming) ? e.upcoming : []) {
        const w = document.createElement("p");
        w.className = "small";
        const b = document.createElement("strong");
        b.textContent = "Upcoming rule change";
        w.append(b, `, effective ${new Date(u.effective_from).toUTCString()} (sha256 ${String(u.sha256).slice(0, 16)}…).`);
        box.append(w);
      }
    })
    .catch(() => {});
})();
