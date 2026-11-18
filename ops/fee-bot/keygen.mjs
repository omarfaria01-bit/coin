#!/usr/bin/env node
// Create the fee bot wallet ON THE SERVER. Writes the secret key to a 0600 file and prints only
// the public address. Refuses to overwrite. Never run this anywhere else; never copy the file.
// Usage: node keygen.mjs /etc/coin/fee-bot/keypair.json
import fs from "node:fs";

import { Keypair } from "@solana/web3.js";

const file = process.argv[2];
if (!file) throw new Error("usage: node keygen.mjs <keypair.json>");
const kp = Keypair.generate();
const fd = fs.openSync(file, "wx", 0o600); // fails if the file exists
fs.writeSync(fd, JSON.stringify(Array.from(kp.secretKey)));
fs.closeSync(fd);
kp.secretKey.fill(0);
console.log(kp.publicKey.toBase58());
