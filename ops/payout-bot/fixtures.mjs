import crypto from "node:crypto";

export const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export const b58 = (bytes) => {
  let n = BigInt(`0x${Buffer.from(bytes).toString("hex")}`);
  let s = "";
  for (; n > 0n; n /= 58n) s = B58[Number(n % 58n)] + s;
  for (const b of bytes) if (b === 0) s = `1${s}`; else break;
  return s;
};
export const key = () => b58(crypto.randomBytes(32));
export const SYS = key();
export const MINT_A = key(); // SPL
export const MINT_B = key(); // Token-2022
export const HOLDERS = [key(), key(), key()];
export const DAY = "2026-11-19";

export function makePlan() {
  const transfers = [];
  for (const [mint, amts] of [[MINT_A, ["500", "300", "150"]], [MINT_B, ["70", "20"]]]) {
    amts.forEach((a, i) => transfers.push({ wallet: HOLDERS[i], mint, amount: a, memo: `GTASP10:pay:${DAY}:${HOLDERS[i]}:${mint}` }));
  }
  return {
    schema: 1, day: DAY, system_wallet: SYS, transfers,
    carried: [{ wallet: HOLDERS[2], mint: MINT_B, amount: "10" }],
    excluded: [{ wallet: SYS, reason: "system" }],
    totals: { [MINT_A]: { accrued: "950", paid: "950", carried: "0" }, [MINT_B]: { accrued: "100", paid: "90", carried: "10" } },
  };
}

