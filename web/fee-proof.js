// Proof box: link the pump.fun fee-sharing transaction once FEE_SHARING_TX is set in config.js. Text only.
(() => {
  const el = document.getElementById("fee-sharing-tx");
  const tx = typeof FEE_SHARING_TX === "string" ? FEE_SHARING_TX : "";
  if (!el || !/^[1-9A-HJ-NP-Za-km-z]{64,90}$/.test(tx)) return;
  const a = document.createElement("a");
  a.href = `https://solscan.io/tx/${encodeURIComponent(tx)}`;
  a.target = "_blank";
  a.rel = "noopener";
  a.className = "mono";
  a.textContent = `${tx.slice(0, 8)}…${tx.slice(-8)} on Solscan`;
  el.textContent = "";
  el.append(a);
})();
