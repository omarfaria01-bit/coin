"""Turn recorded Solana jsonParsed transactions into TokenEvent / SolTransfer.

Offline only: no network, no RPC, no wallet or key handling. Pad-agnostic —
BUY/SELL/TRANSFER come from pre/post balances (native SOL + WSOL vs the
target mint) plus which side signed, not from a launchpad program id.

Token-2022 transfer fees: the destination is credited the received amount;
the withheld fee is a second TRANSFER to a visible fee account, otherwise
to the mint (withheld sink). Amounts are always ints.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from engine.types import EventKind, SolTransfer, TokenEvent, WalletId

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SYSTEM = "11111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111112"
_TOKEN_PROGS = frozenset({TOKEN_PROGRAM, TOKEN_2022, "spl-token", "spl-token-2022"})
_XFER = frozenset({"transfer", "transferChecked", "transferCheckedWithFee"})


class ParseError(ValueError):
    """Malformed or unusable jsonParsed transaction."""


def _int(name: str, value: Any) -> int:
    if isinstance(value, (bool, float)):
        raise ParseError(f"{name} must be an int, got {type(value).__name__}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ParseError(f"{name} must be an int, got {value!r}")


def _obj(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParseError(f"{name} must be an object, got {type(value).__name__}")
    return value


def _unwrap(blob: Mapping[str, Any]) -> Mapping[str, Any]:
    if "result" in blob and "transaction" not in blob:
        if blob["result"] is None:
            raise ParseError("transaction result is null")
        return _obj("result", blob["result"])
    return blob


def _pk(entry: Any) -> str:
    if isinstance(entry, str) and entry:
        return entry
    if isinstance(entry, Mapping) and entry.get("pubkey"):
        return str(entry["pubkey"])
    raise ParseError(f"cannot read account pubkey from {entry!r}")


def _keys_and_signers(
    tx: Mapping[str, Any], meta: Mapping[str, Any]
) -> tuple[list[str], frozenset[str]]:
    message = _obj("transaction.message", _obj("transaction", tx.get("transaction")).get("message"))
    raw = list(message.get("accountKeys") or [])
    keys = [_pk(k) for k in raw]
    signers = [_pk(k) for k in raw if isinstance(k, Mapping) and k.get("signer")]
    loaded = meta.get("loadedAddresses") or {}
    if isinstance(loaded, Mapping):
        for group in ("writable", "readonly"):
            keys.extend(_pk(k) for k in (loaded.get(group) or []))
    if not keys:
        raise ParseError("transaction has no accountKeys")
    if not signers:
        signers = [keys[0]]  # legacy string-key layout: first account is the fee payer
    return keys, frozenset(signers)


def _mint_rows(meta: Mapping[str, Any], mint: str) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for side in ("pre", "post"):
        entries = meta.get(f"{side}TokenBalances")
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise ParseError(f"{side}TokenBalances must be a list")
        for i, raw in enumerate(entries):
            entry = _obj(f"{side}TokenBalances[{i}]", raw)
            if entry.get("mint") != mint:
                continue
            idx = _int("accountIndex", entry.get("accountIndex"))
            ui = _obj("uiTokenAmount", entry.get("uiTokenAmount"))
            qty = _int("uiTokenAmount.amount", ui.get("amount"))
            owner = entry.get("owner")
            if not isinstance(owner, str) or not owner:
                raise ParseError(f"{side}TokenBalances accountIndex={idx} missing owner")
            rec = rows.setdefault(idx, {"owner": owner, "pre": 0, "post": 0})
            if rec["owner"] != owner:
                raise ParseError(f"token account index {idx} owner changed between pre and post")
            rec[side] = qty
    return rows


def _ixs(tx: Mapping[str, Any], meta: Mapping[str, Any]) -> list[tuple[int, Mapping[str, Any]]]:
    message = _obj("transaction.message", _obj("transaction", tx.get("transaction")).get("message"))
    out: list[tuple[int, Mapping[str, Any]]] = []
    for i, ix in enumerate(message.get("instructions") or []):
        out.append((i, _obj(f"instructions[{i}]", ix)))
    for group in meta.get("innerInstructions") or []:
        g = _obj("innerInstructions[]", group)
        parent = _int("innerInstructions.index", g.get("index"))
        for j, ix in enumerate(g.get("instructions") or []):
            out.append((parent * 1000 + (j + 1), _obj(f"inner[{parent}][{j}]", ix)))
    return out


def _prog(ix: Mapping[str, Any], keys: Sequence[str]) -> str:
    if ix.get("programId"):
        return str(ix["programId"])
    if ix.get("program") in _TOKEN_PROGS or ix.get("program") == "system":
        return str(ix["program"])
    if "programIdIndex" in ix:
        idx = _int("programIdIndex", ix["programIdIndex"])
        if 0 <= idx < len(keys):
            return keys[idx]
    return ""


def _token_xfer(ix: Mapping[str, Any], mint: str) -> tuple[str, str, int, int] | None:
    parsed = ix.get("parsed")
    if not isinstance(parsed, Mapping) or parsed.get("type") not in _XFER:
        return None
    info = _obj("parsed.info", parsed.get("info"))
    if info.get("mint") not in (None, mint):
        return None
    src, dst = info.get("source"), info.get("destination")
    if not isinstance(src, str) or not isinstance(dst, str):
        raise ParseError("token transfer missing source or destination")
    if "tokenAmount" in info:
        amount = _int("tokenAmount.amount", _obj("tokenAmount", info["tokenAmount"]).get("amount"))
    else:
        amount = _int("amount", info.get("amount"))
    fee = 0
    if "feeAmount" in info:
        fee = _int("feeAmount.amount", _obj("feeAmount", info["feeAmount"]).get("amount"))
    if amount <= 0 or fee < 0 or fee >= amount:
        raise ParseError(f"invalid transfer amount={amount} fee={fee}")
    return src, dst, amount, fee


def _sol_xfer(ix: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, str, int] | None:
    parsed = ix.get("parsed")
    if not isinstance(parsed, Mapping) or parsed.get("type") != "transfer":
        return None
    if _prog(ix, keys) not in ("", SYSTEM, "system"):
        return None
    info = _obj("parsed.info", parsed.get("info"))
    src, dst = info.get("source"), info.get("destination")
    if not isinstance(src, str) or not isinstance(dst, str):
        raise ParseError("system transfer missing source or destination")
    qty = _int("lamports", info.get("lamports"))
    if qty <= 0:
        raise ParseError(f"system transfer lamports must be > 0, got {qty}")
    return src, dst, qty


def _owner(acc: str, keys: Sequence[str], rows: Mapping[int, dict[str, Any]]) -> str:
    try:
        idx = keys.index(acc)
    except ValueError:
        raise ParseError(f"token account {acc} not in accountKeys") from None
    if idx not in rows:
        raise ParseError(f"no token-balance owner for account {acc}")
    return str(rows[idx]["owner"])


def _sol_like(
    owner: str,
    keys: Sequence[str],
    pre: Sequence[int],
    post: Sequence[int],
    fee_payer: str,
    fee: int,
    wsol: Mapping[str, int],
) -> int:
    adj = wsol.get(owner, 0)
    try:
        idx = keys.index(owner)
    except ValueError:
        return adj
    delta = post[idx] - pre[idx]
    if owner == fee_payer:
        delta += fee
    return adj + delta


def _kind(
    src: WalletId, dst: WalletId, sol_src: int, sol_dst: int, signers: frozenset[str]
) -> EventKind:
    swap = (sol_src > 0 and sol_dst <= 0) or (sol_src == 0 and sol_dst < 0)
    if not swap:
        return EventKind.TRANSFER
    # Signers are wallets; the pool/curve PDA does not sign. This is pad-agnostic.
    if dst in signers and src not in signers:
        return EventKind.BUY
    if src in signers and dst not in signers:
        return EventKind.SELL
    if dst in signers and sol_dst < 0:
        return EventKind.BUY
    if src in signers and sol_src > 0:
        return EventKind.SELL
    return EventKind.BUY if sol_dst < 0 else EventKind.SELL


def parse_tx(
    blob: Mapping[str, Any], mint: str
) -> tuple[tuple[TokenEvent, ...], tuple[SolTransfer, ...]]:
    """Parse one recorded jsonParsed getTransaction value for `mint`."""
    if not isinstance(blob, Mapping):
        raise ParseError("transaction must be a JSON object")
    if not isinstance(mint, str) or not mint:
        raise ParseError("mint is required")
    tx = _unwrap(blob)
    meta = _obj("meta", tx.get("meta"))
    slot = _int("slot", tx.get("slot"))
    if tx.get("blockTime") is None:
        raise ParseError("blockTime is required (no wall clock fallback)")
    ts = _int("blockTime", tx.get("blockTime"))
    signatures = _obj("transaction", tx.get("transaction")).get("signatures") or []
    if not signatures or not isinstance(signatures[0], str) or not signatures[0]:
        raise ParseError("transaction has no signatures")
    sig = signatures[0]
    keys, signers = _keys_and_signers(tx, meta)
    fee_payer = keys[0]
    fee = _int("meta.fee", meta.get("fee") or 0)
    pre_sol = [_int(f"preBalances[{i}]", b) for i, b in enumerate(meta.get("preBalances") or [])]
    post_sol = [_int(f"postBalances[{i}]", b) for i, b in enumerate(meta.get("postBalances") or [])]
    if len(pre_sol) != len(keys) or len(post_sol) != len(keys):
        raise ParseError("pre/postBalances length must match accountKeys")
    if meta.get("err") is not None:
        return (), ()

    rows = _mint_rows(meta, mint)
    wsol_delta: dict[str, int] = {}
    for rec in _mint_rows(meta, WSOL).values():
        wsol_delta[rec["owner"]] = wsol_delta.get(rec["owner"], 0) + rec["post"] - rec["pre"]

    events: list[TokenEvent] = []
    sols: list[SolTransfer] = []
    n_parsed = 0
    for ix_n, ix in _ixs(tx, meta):
        prog = _prog(ix, keys)
        if prog in _TOKEN_PROGS:
            parts = _token_xfer(ix, mint)
            if parts is None:
                continue
            src_acc, dst_acc, amount, xfee = parts
            src, dst = _owner(src_acc, keys, rows), _owner(dst_acc, keys, rows)
            received = amount - xfee
            sol_src = _sol_like(src, keys, pre_sol, post_sol, fee_payer, fee, wsol_delta)
            sol_dst = _sol_like(dst, keys, pre_sol, post_sol, fee_payer, fee, wsol_delta)
            kind = _kind(src, dst, sol_src, sol_dst, signers)
            if kind is EventKind.BUY:
                paid = abs(sol_dst) or abs(sol_src)
                events.append(
                    TokenEvent(slot, ts, sig, ix_n, kind, None, dst, received, paid, fee_payer)
                )
            elif kind is EventKind.SELL:
                got = abs(sol_src) or abs(sol_dst)
                events.append(
                    TokenEvent(slot, ts, sig, ix_n, kind, src, None, amount, got, fee_payer)
                )
            else:
                events.append(
                    TokenEvent(slot, ts, sig, ix_n, kind, src, dst, received, None, fee_payer)
                )
                if xfee:
                    sink = mint
                    for idx, rec in rows.items():
                        owner, delta = rec["owner"], rec["post"] - rec["pre"]
                        if owner not in {src, dst} and delta == xfee and idx < len(keys):
                            sink = rec["owner"]
                            break
                    events.append(
                        TokenEvent(
                            slot,
                            ts,
                            sig,
                            ix_n + 1,
                            EventKind.TRANSFER,
                            src,
                            sink,
                            xfee,
                            None,
                            fee_payer,
                        )
                    )
            n_parsed += 1
        moved = _sol_xfer(ix, keys)
        if moved is not None:
            s, d, lamports = moved
            sols.append(SolTransfer(slot, ts, sig, s, d, lamports))

    if n_parsed == 0 and any(rec["post"] != rec["pre"] for rec in rows.values()):
        raise ParseError("mint balances changed but no parsed token transfer was found")

    events.sort(key=lambda e: (e.slot, e.sig, e.ix))
    sols.sort(key=lambda s: (s.slot, s.sig, s.src, s.dst))
    return tuple(events), tuple(sols)


def parse_tx_file(path: Path, mint: str) -> tuple[tuple[TokenEvent, ...], tuple[SolTransfer, ...]]:
    try:
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParseError(f"{path}: invalid JSON: {exc}") from None
    if not isinstance(blob, Mapping):
        raise ParseError(f"{path}: top-level value must be an object")
    return parse_tx(blob, mint)
