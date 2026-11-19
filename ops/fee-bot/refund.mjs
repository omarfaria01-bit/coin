#!/usr/bin/env node
// One-off: send the whole system wallet balance to one address (project closed, kiwi's decision 18 Nov 2026).
// Dry by default: prints the balance and what would be sent. Add --live to sign and send.
// Same safety as run.mjs: key read from the 0600 file and never printed; RPC URL never printed.
//
// Usage: node refund.mjs --to <address> [--live]
import { Connection, PublicKey, SystemProgram, Transaction, sendAndConfirmTransaction } from "@solana/web3.js";

import { loadKeypair } from "./run.mjs";

const FEE = 5000n; // one signature

export function refundAmount(balance) {
  return balance > FEE ? balance - FEE : 0n;
}

async function main(argv) {
  const i = argv.indexOf("--to");
  if (i < 0 || !argv[i + 1]) throw new Error("usage: refund.mjs --to <address> [--live]");
  const to = new PublicKey(argv[i + 1]);
  const live = argv.includes("--live");
  const key = process.env.HELIUS_API_KEY;
  if (!key) throw new Error("HELIUS_API_KEY is not set");
  const wallet = loadKeypair(process.env.FEE_BOT_KEYPAIR ?? "/etc/coin/fee-bot/keypair.json");
  const connection = new Connection(`https://mainnet.helius-rpc.com/?api-key=${key}`, "confirmed");
  const balance = BigInt(await connection.getBalance(wallet.publicKey, "confirmed"));
  const amount = refundAmount(balance);
  console.log(JSON.stringify({ from: wallet.publicKey.toBase58(), to: to.toBase58(), balance: String(balance), send: String(amount), live }));
  if (!live || amount === 0n) return;
  const tx = new Transaction().add(SystemProgram.transfer({ fromPubkey: wallet.publicKey, toPubkey: to, lamports: amount }));
  const sig = await sendAndConfirmTransaction(connection, tx, [wallet], { commitment: "confirmed" });
  console.log(JSON.stringify({ sent: String(amount), sig, solscan: `https://solscan.io/tx/${sig}` }));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv.slice(2)).catch((err) => {
    console.error(JSON.stringify({ error: String(err?.message ?? err).replace(/api-key=[^&\s]+/g, "api-key=***") }));
    process.exit(1);
  });
}
