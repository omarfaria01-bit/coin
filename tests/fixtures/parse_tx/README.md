Synthetic jsonParsed `getTransaction` fixtures for `adapters/parse_tx.py`.
Hand-written (generated offline); no RPC was used. Addresses are
`sim.agents.wallet_id("parse-…")` labels, not real wallets. Covers buy,
sell, transfer, Token-2022 transfer fee, multi-ix, failed tx, SOL-only
transfer, an inner-ix (aggregator-style) buy wrapped in an RPC envelope, and a buy whose SOL leg is WSOL (`buy_wsol.json`).
