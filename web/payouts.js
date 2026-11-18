// Latest holder payouts (D46), from data/payouts.json written by the payout bot. Text only, no HTML.
(() => {
  const box = document.getElementById("payouts");
  if (!box) return;
  const short = (a) => `${a.slice(0, 4)}…${a.slice(-4)}`;
  const link = (href, text) => {
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = text;
    return a;
  };
  fetch(`data/payouts.json?t=${Date.now()}`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      const days = d && Array.isArray(d.days) ? d.days : []; // newest day first
      const rows = days.flatMap((x) => (Array.isArray(x.transfers) ? x.transfers : [])).slice(0, 50);
      if (!rows.length) return;
      box.textContent = "";
      if (d.wallet) {
        const p = document.createElement("p");
        p.className = "small muted";
        p.append("System wallet: ", link(`https://solscan.io/account/${encodeURIComponent(d.wallet)}`, short(d.wallet)));
        box.append(p);
      }
      for (const r of rows) {
        const div = document.createElement("div");
        div.className = "rw-row";
        const who = document.createElement("span");
        who.className = "mono";
        who.textContent = short(String(r.wallet));
        const amt = document.createElement("span");
        amt.className = "mono small";
        amt.textContent = `${r.amount} of ${short(String(r.mint))}`;
        const tx = String(r.sig).length > 40 ? link(`https://solscan.io/tx/${encodeURIComponent(r.sig)}`, "tx") : document.createElement("span");
        div.append(who, amt, tx);
        box.append(div);
      }
    })
    .catch(() => {});
})();
