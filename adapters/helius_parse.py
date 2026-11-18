"""Turn recorded Helius JSON into the dicts `market_data` already understands.

No HTTP here. Token names and descriptions are data: nothing in them is fetched
or followed. Checked against the Parsed Events response reference on 2026-11-17.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

# getTipAccounts, https://docs.jito.wtf/lowlatencytxnsend/ (2026-11-17).
JITO_TIP_ACCOUNTS = frozenset(
    {
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
        "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
        "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
        "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
        "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
        "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
    }
)
INCINERATOR = "1nc1nerator11111111111111111111111111111111"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_CREATE_NAMES = frozenset({"create", "create_v2"})
POOL_PROGRAMS = frozenset(
    {
        PUMP_PROGRAM,
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",  # pump.fun AMM
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
        "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # Raydium CPMM
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # Raydium CLMM
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora DLMM
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpool
    }
)
_MINT_KEYS = ("mint", "mint_account", "token_mint")
_CREATOR_KEYS = ("user", "creator", "creator_account")
_CURVE_KEYS = ("bonding_curve", "bondingCurve")


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _text(value: object, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    return value[:limit]


def normalize_transaction(item: Mapping[str, object]) -> dict[str, object] | None:
    """One Parsed Events result → the fee/bundle shape. Malformed items are skipped."""
    parsed = item.get("parsed")
    if not isinstance(parsed, Mapping):
        return None
    signature = item.get("signature")
    if not isinstance(signature, str) or not signature:
        return None
    fee = parsed.get("fee")
    tips = _tips(parsed.get("nativeTransfers"))
    ok = item.get("parserStatus") == "OK" and parsed.get("transactionStatus") == "OK"
    summary = parsed.get("summary")
    kind = summary.get("type") if isinstance(summary, Mapping) else None
    when = parsed.get("blockTime")
    slot = parsed.get("slot")
    return {
        "signature": signature,
        "slot": slot if isinstance(slot, int) else None,
        "block_time": when if isinstance(when, int) else None,
        "ok": ok,
        "fee": fee if _int(fee) is not None else None,
        "tips": tips,
        "fee_payer": parsed.get("feePayer") if isinstance(parsed.get("feePayer"), str) else None,
        "summary": kind if isinstance(kind, str) else None,
        "transfers": _transfers(parsed.get("tokenTransfers")),
        "sol_out": _payer_sol(parsed.get("nativeTransfers"), parsed.get("feePayer"), "out"),
        "sol_in": _payer_sol(parsed.get("nativeTransfers"), parsed.get("feePayer"), "in"),
        "creates": _creates(parsed.get("instructions"), when, slot),
    }


_SLIM_TOP = ("signature", "parserStatus", "block_time", "blockTime", "timestamp")
_SLIM_PARSED = ("fee", "transactionStatus", "blockTime", "slot", "feePayer")
_SLIM_NATIVE = ("fromUserAccount", "toUserAccount", "amount")
_SLIM_TOKEN = ("mint", "fromUserAccount", "toUserAccount", "rawTokenAmount")


def _pick(row: object, keys: Sequence[str]) -> object:
    if not isinstance(row, Mapping):
        return row
    return {k: row[k] for k in keys if k in row}


def slim_item(item: object) -> object:
    """#311: drop what normalize_transaction never reads, so the history cache stays small.

    Invariant (tested): normalize_transaction(slim_item(x)) == normalize_transaction(x).
    Only pump.fun create instructions survive; account data, logs and other programs go.
    """
    if not isinstance(item, Mapping):
        return item
    out: dict[str, object] = {k: item[k] for k in _SLIM_TOP if k in item}
    parsed = item.get("parsed")
    if not isinstance(parsed, Mapping):
        if "parsed" in item:
            out["parsed"] = parsed
        return out
    p: dict[str, object] = {k: parsed[k] for k in _SLIM_PARSED if k in parsed}
    summary = parsed.get("summary")
    if isinstance(summary, Mapping):
        p["summary"] = {"type": summary.get("type")}
    elif "summary" in parsed:
        p["summary"] = summary
    for key, keys in (("nativeTransfers", _SLIM_NATIVE), ("tokenTransfers", _SLIM_TOKEN)):
        if key in parsed:
            rows = parsed[key]
            p[key] = [_pick(r, keys) for r in rows] if isinstance(rows, list) else rows
    ixs = parsed.get("instructions")
    if isinstance(ixs, list):
        keep = []
        for ix in ixs:
            if not isinstance(ix, Mapping) or ix.get("programId") != PUMP_PROGRAM:
                continue
            if ix.get("instructionName") not in PUMP_CREATE_NAMES:
                continue
            dec = ix.get("decoded")
            slim_ix: dict[str, object] = {
                "programId": ix["programId"],
                "instructionName": ix["instructionName"],
            }
            if isinstance(dec, Mapping):
                args = dec.get("args")
                slim_ix["decoded"] = {
                    "args": _pick(args, ("name", "symbol")),
                    "accounts": dec.get("accounts"),
                }
            elif "decoded" in ix:
                slim_ix["decoded"] = dec
            keep.append(slim_ix)
        p["instructions"] = keep
    elif "instructions" in parsed:
        p["instructions"] = ixs
    out["parsed"] = p
    return out


def _tips(raw: object) -> int | None:
    if raw is None:
        return 0
    if not isinstance(raw, list):
        return None
    total = 0
    for row in raw:
        if not isinstance(row, Mapping) or row.get("toUserAccount") not in JITO_TIP_ACCOUNTS:
            continue
        amount = _int(row.get("amount"))
        if amount is None:
            return None
        total += amount
    return total


def _payer_sol(raw: object, payer: object, way: str) -> int | None:
    """Lamports the fee payer sent ("out", tips excluded) or received ("in") in native transfers."""
    if not isinstance(raw, list) or not isinstance(payer, str):
        return None
    src, dst = (
        ("fromUserAccount", "toUserAccount")
        if way == "out"
        else ("toUserAccount", "fromUserAccount")
    )
    total = 0
    for row in raw:
        if (
            not isinstance(row, Mapping)
            or row.get(src) != payer
            or row.get(dst) in JITO_TIP_ACCOUNTS
        ):
            continue
        amount = _int(row.get("amount"))
        if amount is None:
            return None
        total += amount
    return total


def _transfers(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, object]] = []
    for row in raw:
        if not isinstance(row, Mapping) or not isinstance(row.get("mint"), str):
            continue
        amount = row.get("rawTokenAmount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            continue
        out.append(
            {
                "mint": row["mint"],
                "from": _str(row.get("fromUserAccount")),
                "to": _str(row.get("toUserAccount")),
                "amount": amount,
            }
        )
    return out


def _creates(raw: object, when: object, slot: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, object]] = []
    for ix in raw:
        if not isinstance(ix, Mapping):
            continue
        name = ix.get("instructionName")
        if ix.get("programId") != PUMP_PROGRAM or name not in PUMP_CREATE_NAMES:
            continue
        decoded = ix.get("decoded") if isinstance(ix.get("decoded"), Mapping) else {}
        args = decoded.get("args") if isinstance(decoded.get("args"), Mapping) else {}
        accounts = _accounts(decoded.get("accounts"))
        mint = _first(accounts, _MINT_KEYS)
        creator = _first(accounts, _CREATOR_KEYS)
        if not mint or not creator:
            continue
        out.append(
            {
                "mint": mint,
                "name": _text(args.get("name")),
                "symbol": _text(args.get("symbol")),
                "creator": creator,
                "bonding_curve": _first(accounts, _CURVE_KEYS),
                "block_time": when if isinstance(when, int) else None,
                "slot": slot if isinstance(slot, int) else None,
            }
        )
    return out


def _accounts(raw: object) -> dict[str, str]:
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for row in raw:
        key = row.get("name") if isinstance(row, Mapping) else None
        pubkey = row.get("pubkey") if isinstance(row, Mapping) else None
        if isinstance(key, str) and isinstance(pubkey, str):
            out[key] = pubkey
    return out


def _first(accounts: Mapping[str, str], keys: Sequence[str]) -> str | None:
    for key in keys:
        if accounts.get(key):
            return accounts[key]
    return None


def parse_asset(result: Mapping[str, object]) -> dict[str, object]:
    """DAS getAsset. Description is the indexed string only; json_uri is ignored."""
    content = result.get("content") if isinstance(result.get("content"), Mapping) else {}
    meta = content.get("metadata") if isinstance(content.get("metadata"), Mapping) else {}
    token = result.get("token_info") if isinstance(result.get("token_info"), Mapping) else {}
    price_info = token.get("price_info") if isinstance(token.get("price_info"), Mapping) else {}
    price = price_info.get("price_per_token")
    creators = result.get("creators")
    creator = None
    first = creators[0] if isinstance(creators, list) and creators else None
    if isinstance(first, Mapping) and isinstance(first.get("address"), str):
        creator = first["address"]
    return {
        "name": _text(meta.get("name")),
        "symbol": _text(meta.get("symbol")),
        "description": _text(meta.get("description"), 500),
        "price": price if isinstance(price, (int, float)) and not isinstance(price, bool) else None,
        "creator": creator,
    }


def parse_mint_account(value: Mapping[str, object] | None) -> dict[str, object] | None:
    """getAccountInfo value for a mint. Missing parsed info → None."""
    if not isinstance(value, Mapping):
        return None
    data = value.get("data")
    parsed = data.get("parsed") if isinstance(data, Mapping) else None
    info = parsed.get("info") if isinstance(parsed, Mapping) else None
    if not isinstance(info, Mapping):
        return None
    try:
        supply = int(str(info["supply"]))
        decimals = int(str(info["decimals"]))
    except (KeyError, TypeError, ValueError):
        return None
    if supply < 0 or decimals < 0:
        return None
    program = value.get("owner") if isinstance(value.get("owner"), str) else None
    return {"program": program, "supply": supply, "decimals": decimals, "info": dict(info)}


def parse_largest(
    rows: Sequence[Mapping[str, object]] | None,
    accounts: Sequence[object] | None,
) -> list[tuple[str | None, int]] | None:
    """getTokenLargestAccounts rows plus the matching getMultipleAccounts values."""
    if not isinstance(rows, Sequence) or not isinstance(accounts, Sequence):
        return None
    if len(rows) != len(accounts):
        return None
    out: list[tuple[str | None, int]] = []
    for row, account in zip(rows, accounts, strict=True):
        if not isinstance(row, Mapping):
            return None
        try:
            amount = int(str(row["amount"]))
        except (KeyError, TypeError, ValueError):
            return None
        owner: str | None = None
        if isinstance(account, Mapping):
            data = account.get("data")
            parsed = data.get("parsed") if isinstance(data, Mapping) else None
            info = parsed.get("info") if isinstance(parsed, Mapping) else None
            if isinstance(info, Mapping) and isinstance(info.get("owner"), str):
                owner = info["owner"]
        out.append((owner, amount))
    return out


def excluded_owners(
    *,
    hubs: Iterable[str],
    curves: Iterable[str | None],
    owner_programs: Mapping[str, str | None],
    treasury: str | None,
) -> set[str]:
    """Burn, hubs, curve PDAs, AMM-owned accounts, and the index treasury when known."""
    out = {INCINERATOR, *hubs}
    out.update(c for c in curves if c)
    if treasury:
        out.add(treasury)
    for owner, program in owner_programs.items():
        if program in POOL_PROGRAMS:
            out.add(owner)
    return out
