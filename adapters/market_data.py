"""Read-only market data adapter for the GTA 6 index (INDEX_RULES.md §1–§3, issue #161).

Sources: DexScreener for discovery, market cap, liquidity and volume; Solana JSON-RPC for
mint authorities and holder accounts; Helius Parsed Events (optional key) for unique traders.
No signing, no writes, no clock: every collector takes the sample time `ts`. Token names,
tickers and descriptions are untrusted data and are never interpreted as instructions.

Samples are plain JSON records, append-only, stored by `tools/run_index.py` in
`data/index/samples/<date>.jsonl` (gitignored). `aggregate` is pure and does all the maths.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import base58

from adapters.hubs import load_hubs
from index.filters import Metrics, keyword_hit
from index.params import IndexParams, Overrides

DEXSCREENER = "https://api.dexscreener.com"
HELIUS = "https://mainnet.helius-rpc.com"
DEXSCREENER_BATCH = 30  # documented limit for /tokens/v1
BURN_ADDRESSES = frozenset(
    {
        "1nc1nerator11111111111111111111111111111111",
        "11111111111111111111111111111111",
    }
)
# Owner program of a token account's authority when that authority is a pool/curve vault.
# A wrong id can only fail to exclude a vault (top10 looks higher, coin is filtered out), never
# the other way round.
POOL_PROGRAMS = frozenset(
    {
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # pump.fun curve
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",  # pumpswap
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
        "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # Raydium CPMM
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca Whirlpool
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora DLMM
    }
)

Opener = Callable[[str], Any]
Poster = Callable[[str, Any], Any]


# ------------------------------------------------------------------ HTTP


def require_https(url: str) -> str:
    """Return url if it is an https URL with a host; else ValueError (blocks file:, http:, ...)."""
    parsed = urlparse(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"only https URLs are allowed, got {url!r}")
    return url


def get_json(url: str, timeout: float = 20.0) -> Any:
    require_https(url)
    req = Request(url, headers={"User-Agent": "coin-index/0.1", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https bases
        return json.loads(resp.read().decode())


def post_json(url: str, payload: Any, timeout: float = 30.0) -> Any:
    require_https(url)
    req = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "coin-index/0.1"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https bases
        return json.loads(resp.read().decode())


def rpc(url: str, method: str, params: Sequence[Any], *, poster: Poster = post_json) -> Any:
    """One read-only JSON-RPC call. Raises RuntimeError on an RPC error payload."""
    payload = poster(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)})
    if isinstance(payload, Mapping) and payload.get("error"):
        raise RuntimeError(f"RPC error on {method}: {payload['error']}")
    return payload.get("result") if isinstance(payload, Mapping) else None


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _num(value: object) -> float | None:
    """Finite float or None. Strings from DexScreener are accepted."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ DexScreener


def search(keyword: str, *, opener: Opener = get_json) -> list[dict]:
    """`GET /latest/dex/search` filtered to Solana pairs."""
    data = opener(f"{DEXSCREENER}/latest/dex/search?q={quote(keyword)}")
    pairs = data.get("pairs") if isinstance(data, Mapping) else None
    return [p for p in pairs or [] if isinstance(p, Mapping) and p.get("chainId") == "solana"]


def tokens(mints: Sequence[str], *, opener: Opener = get_json) -> list[dict]:
    """`GET /tokens/v1/solana/{mints}` in documented batches of at most 30."""
    out: list[dict] = []
    for chunk in _chunks(sorted(set(mints)), DEXSCREENER_BATCH):
        if not chunk:
            continue
        data = opener(f"{DEXSCREENER}/tokens/v1/solana/{','.join(chunk)}")
        out.extend(p for p in data or [] if isinstance(p, Mapping) and p.get("chainId") == "solana")
    return out


def _liquidity(pair: Mapping) -> float:
    liq = pair.get("liquidity")
    return _num(liq.get("usd")) if isinstance(liq, Mapping) and _num(liq.get("usd")) else 0.0


def _valid_mint(mint: str) -> bool:
    try:
        return len(base58.b58decode(mint)) == 32
    except ValueError:
        return False


def best_pairs(pairs: Iterable[Mapping]) -> dict[str, dict]:
    """One pair per base-token mint: the most liquid one. Invalid mints are dropped."""
    out: dict[str, dict] = {}
    for pair in pairs:
        base = pair.get("baseToken")
        mint = base.get("address") if isinstance(base, Mapping) else None
        if not isinstance(mint, str) or not _valid_mint(mint):
            continue
        if mint not in out or _liquidity(pair) > _liquidity(out[mint]):
            out[mint] = dict(pair)
    return out


def discover(
    params: IndexParams, overrides: Overrides, *, opener: Opener = get_json
) -> dict[str, dict]:
    """Poll DexScreener for every strong keyword; keep strong and weak keyword hits.

    DexScreener pair data has no description, so discovery matches name + ticker only.
    Weak hits are kept so `run_index` can list them for kiwi's review. `allow` mints are
    added even when no keyword matches (INDEX_RULES §1).
    """
    keywords = (*params.keywords.strong, *params.keywords.weak)
    found: list[dict] = []
    for keyword in params.keywords.strong:
        found.extend(search(keyword, opener=opener))
    by_mint = best_pairs(
        pair for pair in found if any(keyword_hit(_text(pair), k) for k in keywords)
    )
    allow = [e.mint for e in overrides.allow if e.mint not in by_mint]
    if allow:
        fetched = best_pairs(tokens(allow, opener=opener))
        by_mint.update({m: p for m, p in fetched.items() if m in allow})
    return by_mint


def _text(pair: Mapping) -> str:
    base = pair.get("baseToken") if isinstance(pair.get("baseToken"), Mapping) else {}
    return f"{base.get('name') or ''} {base.get('symbol') or ''}"


def market_record(pair: Mapping, ts: int) -> dict:
    """One 5-minute sample for one mint."""
    base = pair["baseToken"]
    liquidity = pair.get("liquidity") if isinstance(pair.get("liquidity"), Mapping) else {}
    volume = pair.get("volume") if isinstance(pair.get("volume"), Mapping) else {}
    return {
        "kind": "market",
        "ts": int(ts),
        "mint": base["address"],
        "ticker": str(base.get("symbol") or ""),
        "name": str(base.get("name") or ""),
        "description": "",
        "price_usd": _num(pair.get("priceUsd")),
        "market_cap_usd": _num(pair.get("marketCap")),
        "liquidity_usd": _num(liquidity.get("usd")),
        "volume_h24_usd": _num(volume.get("h24")),
        "pair_created_at": pair.get("pairCreatedAt"),
    }


# ------------------------------------------------------------------ Solana RPC


def mint_facts(rpc_url: str, mint: str, ts: int, *, poster: Poster = post_json) -> dict | None:
    """F8 authorities and the owner program (SPL vs Token-2022, #18)."""
    res = rpc(rpc_url, "getAccountInfo", [mint, {"encoding": "jsonParsed"}], poster=poster)
    value = res.get("value") if isinstance(res, Mapping) else None
    if not isinstance(value, Mapping):
        return None
    data = value.get("data") if isinstance(value.get("data"), Mapping) else {}
    info = (data.get("parsed") or {}).get("info") or {}
    if "mintAuthority" not in info or "freezeAuthority" not in info:
        return None  # malformed response: never report "revoked" by accident
    return {
        "kind": "launch",
        "ts": int(ts),
        "mint": mint,
        "mint_authority_revoked": info.get("mintAuthority") is None,
        "freeze_authority_revoked": info.get("freezeAuthority") is None,
        "token_program": data.get("program") or value.get("owner"),
        "supply": info.get("supply"),
        "creator": None,
        "bundle_pct": None,
        "creator_launches_7d": None,
    }


def _token_account_authority(
    rpc_url: str, account: str, *, poster: Poster = post_json
) -> str | None:
    res = rpc(rpc_url, "getAccountInfo", [account, {"encoding": "jsonParsed"}], poster=poster)
    value = res.get("value") if isinstance(res, Mapping) else None
    if not isinstance(value, Mapping):
        return None
    data = value.get("data") if isinstance(value.get("data"), Mapping) else {}
    return ((data.get("parsed") or {}).get("info") or {}).get("owner")


def _is_pool_vault(rpc_url: str, account: str, *, poster: Poster = post_json) -> bool:
    authority = _token_account_authority(rpc_url, account, poster=poster)
    if authority is None:
        return False
    res = rpc(rpc_url, "getAccountInfo", [authority], poster=poster)
    value = res.get("value") if isinstance(res, Mapping) else None
    return isinstance(value, Mapping) and value.get("owner") in POOL_PROGRAMS


def top10_pct(
    rpc_url: str,
    mint: str,
    supply: int,
    *,
    hubs: frozenset[str] = frozenset(),
    excluded: frozenset[str] = frozenset(),
    max_accounts: int = 20,
    poster: Poster = post_json,
) -> float | None:
    """F3: share of supply held by the top 10 accounts, excluding vaults, burn and hubs.

    Pool/curve vaults are detected by the owner program of the vault authority. Returns None
    when the RPC gives no usable data, so the filter fails safe (`insufficient_data`).
    """
    if supply <= 0:
        return None
    res = rpc(rpc_url, "getTokenLargestAccounts", [mint], poster=poster)
    accounts = res.get("value") if isinstance(res, Mapping) else None
    if not isinstance(accounts, list) or not accounts:
        return None
    kept: list[int] = []
    skip = set(excluded) | set(hubs) | set(BURN_ADDRESSES)
    for acc in accounts[: max(1, max_accounts)]:
        address = acc.get("address") if isinstance(acc, Mapping) else None
        amount = acc.get("amount") if isinstance(acc, Mapping) else None
        if not isinstance(address, str) or address in skip:
            continue
        if _is_pool_vault(rpc_url, address, poster=poster):
            continue
        try:
            kept.append(int(amount))
        except (TypeError, ValueError):
            continue
    if len(kept) < 10:  # the true top 10 is unknown: fail safe, never guess low
        return None
    return round(sum(sorted(kept, reverse=True)[:10]) / supply * 100, 6)


def dev_pct(
    rpc_url: str, mint: str, creator: str, supply: int, *, poster: Poster = post_json
) -> float | None:
    """F6: share of supply still held by the creator wallet."""
    if supply <= 0:
        return None
    res = rpc(
        rpc_url,
        "getTokenAccountsByOwner",
        [creator, {"mint": mint}, {"encoding": "jsonParsed"}],
        poster=poster,
    )
    value = res.get("value") if isinstance(res, Mapping) else None
    if not isinstance(value, list):
        return None
    total = 0
    for account in value:
        parsed = ((account.get("account") or {}).get("data") or {}).get("parsed") or {}
        amount = ((parsed.get("info") or {}).get("tokenAmount") or {}).get("amount")
        try:
            total += int(amount)
        except (TypeError, ValueError):
            continue
    return round(total / supply * 100, 6)


# ------------------------------------------------------------------ Helius parsed events


def helius_history(
    api_key: str,
    address: str,
    *,
    since_ts: int | None = None,
    until_ts: int | None = None,
    max_pages: int = 10,
    poster: Poster = post_json,
) -> list[dict]:
    """Parsed Events transaction history for `address` (10 credits/request, Free plan)."""
    url = f"{HELIUS}/v1/parsed-events/transaction-history?api-key={quote(api_key)}"
    body: dict[str, Any] = {
        "address": address,
        "limit": 100,
        "sortOrder": "desc",
        "tokenAccounts": "balanceChanged",
    }
    window = {}
    if since_ts is not None:
        window["gte"] = int(since_ts)
    if until_ts is not None:
        window["lte"] = int(until_ts)
    if window:
        body["time"] = window
    out: list[dict] = []
    token: str | None = None
    for _ in range(max_pages):
        if token:
            body["paginationToken"] = token
        try:
            page = poster(url, body)
        except OSError as exc:  # never let the api-key URL reach a log or traceback
            raise RuntimeError(
                f"Helius history failed for {address}: {exc.__class__.__name__}"
            ) from None
        if not isinstance(page, Mapping):
            break
        out.extend(item for item in page.get("data") or [] if isinstance(item, Mapping))
        token = page.get("paginationToken")
        if not token:
            break
    return out


def _swaps(history: Iterable[Mapping], since_ts: int, until_ts: int) -> list[Mapping]:
    out = []
    for item in history:
        if item.get("parserStatus") != "OK":
            continue
        parsed = item.get("parsed") if isinstance(item.get("parsed"), Mapping) else {}
        summary = parsed.get("summary") if isinstance(parsed.get("summary"), Mapping) else {}
        block_time = parsed.get("blockTime")
        if summary.get("type") != "swap" or not isinstance(block_time, int):
            continue
        if since_ts <= block_time <= until_ts:
            out.append(item)
    return out


def unique_traders(history: Iterable[Mapping], *, since_ts: int, until_ts: int) -> int:
    """F9: distinct fee payers of swap transactions in the window (0 is a real answer)."""
    payers = set()
    for item in _swaps(history, since_ts, until_ts):
        payer = (item.get("parsed") or {}).get("feePayer")
        if isinstance(payer, str) and payer:
            payers.add(payer)
    return len(payers)


def creator_from_history(history: Iterable[Mapping]) -> str | None:
    """Creator = fee payer of the mint's earliest parsed transaction (the create tx)."""
    items = []
    for item in history:
        parsed = item.get("parsed") if isinstance(item.get("parsed"), Mapping) else {}
        payer = parsed.get("feePayer")
        if item.get("parserStatus") == "OK" and isinstance(payer, str) and payer:
            items.append(((parsed.get("blockTime") or 0), str(item.get("signature") or ""), payer))
    return min(items, key=lambda row: (row[0], row[1]))[2] if items else None


# ------------------------------------------------------------------ aggregation


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _latest(records: Sequence[Mapping], key: str) -> tuple[Any, int] | tuple[None, None]:
    best: tuple[Any, int] | tuple[None, None] = (None, None)
    for rec in records:
        value = rec.get(key)
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            continue
        if best[1] is None or int(rec["ts"]) > best[1]:
            best = (value, int(rec["ts"]))
    return best


def aggregate(
    samples: Iterable[Mapping], window_start: int, window_end: int, params: IndexParams
) -> list[Metrics]:
    """Turn raw JSONL records into one `Metrics` per mint. Missing values stay None.

    Coverage = distinct `sample_minutes` buckets present in the mint's window divided by the
    buckets the window should contain (capped at 1). A young token's window starts at its
    first pool/curve (`pair_created_at`), per INDEX_RULES §2.
    """
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    by_mint: dict[str, list[Mapping]] = {}
    for rec in samples:
        if not isinstance(rec, Mapping):
            raise ValueError("each sample must be a mapping")
        mint, kind, ts = rec.get("mint"), rec.get("kind"), rec.get("ts")
        if not isinstance(mint, str) or kind not in {"market", "holders", "launch", "flow"}:
            raise ValueError(f"bad sample: {rec!r}")
        if not isinstance(ts, int) or isinstance(ts, bool):
            raise ValueError(f"bad sample ts: {rec!r}")
        by_mint.setdefault(mint, []).append(rec)

    interval = params.sample_minutes * 60
    out: list[Metrics] = []
    for mint in sorted(by_mint):
        all_records = by_mint[mint]
        records = [r for r in all_records if window_start <= int(r["ts"]) <= window_end]

        def _kind(kind: str, rows: Sequence[Mapping] = records) -> list[Mapping]:
            return [r for r in rows if r["kind"] == kind]

        market = _kind("market")
        if not market:  # no sample in the window -> not a candidate
            continue
        holders = _kind("holders")
        launch = max(_kind("launch", all_records), key=lambda r: int(r["ts"]), default={})
        flow = max(_kind("flow"), key=lambda r: int(r["ts"]), default={})
        meta = market[0] if market else records[0]
        created = market[0].get("pair_created_at") if market else None
        token_start = window_start
        if isinstance(created, int) and not isinstance(created, bool):
            token_start = max(window_start, created // 1000)
        buckets = {int(r["ts"]) // interval for r in market}
        expected = max(1, round((window_end - token_start) / interval))
        coverage = round(min(1.0, len(buckets) / expected), 6) if market else None
        volume, _ = _latest(market, "volume_h24_usd")
        top10 = _median([v for r in holders if (v := _num(r.get("top10_pct"))) is not None])
        dev = _median([v for r in holders if (v := _num(r.get("dev_pct"))) is not None])
        sources: dict[str, str] = {}
        market_ts = max((int(r["ts"]) for r in market), default=None)
        if market_ts is not None:
            for key in ("age_hours", "liquidity_usd", "mc_usd", "volume_usd"):
                sources[key] = f"dexscreener@{_iso(market_ts)}"
        if top10 is not None or dev is not None:
            holder_ts = max((int(r["ts"]) for r in holders), default=None)
            for key in ("top10_pct", "dev_pct"):
                sources[key] = f"solana-rpc@{_iso(holder_ts)}" if holder_ts else "solana-rpc"
        if launch:
            for key in ("mint_authority_revoked", "freeze_authority_revoked"):
                sources[key] = f"solana-rpc@{_iso(int(launch['ts']))}"
        if flow:
            for key in ("unique_traders", "total_fees_sol", "window_fees_sol"):
                sources[key] = f"helius@{_iso(int(flow['ts']))}"
        out.append(
            Metrics(
                mint=mint,
                ticker=str(meta.get("ticker") or ""),
                name=str(meta.get("name") or ""),
                description=str(meta.get("description") or ""),
                coverage=coverage,
                age_hours=(
                    round((window_end - int(created) / 1000) / 3600, 6)
                    if isinstance(created, int)
                    and not isinstance(created, bool)
                    and int(created) / 1000 <= window_end
                    else None
                ),
                liquidity_usd=_mean(
                    [v for r in market if (v := _num(r.get("liquidity_usd"))) is not None]
                ),
                mc_usd=_mean(
                    [v for r in market if (v := _num(r.get("market_cap_usd"))) is not None]
                ),
                top10_pct=top10,
                total_fees_sol=_num(flow.get("total_fees_sol")),
                window_fees_sol=_num(flow.get("window_fees_sol")),
                bundle_pct=_num(launch.get("bundle_pct")),
                dev_pct=dev,
                creator_launches_7d=(
                    int(launch["creator_launches_7d"])
                    if isinstance(launch.get("creator_launches_7d"), int)
                    else None
                ),
                mint_authority_revoked=launch.get("mint_authority_revoked"),
                freeze_authority_revoked=launch.get("freeze_authority_revoked"),
                unique_traders=(
                    int(flow["unique_traders"])
                    if isinstance(flow.get("unique_traders"), int)
                    else None
                ),
                volume_usd=volume,
                sources=sources,
            )
        )
    return out


def read_samples(path: str) -> list[dict]:
    """Read an append-only JSONL sample file; a missing file is an empty history."""
    try:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return []


def append_samples(path: str, records: Iterable[Mapping]) -> int:
    """Append records to a JSONL file (creating parents); returns how many were written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [dict(r) for r in records]
    with target.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return len(rows)


def min_hubs() -> frozenset[str]:
    """The public hubs allowlist, or an empty set if the data file is unavailable."""
    try:
        return load_hubs()
    except (OSError, ValueError):
        return frozenset()


__all__ = [
    "aggregate",
    "append_samples",
    "best_pairs",
    "creator_from_history",
    "dev_pct",
    "discover",
    "helius_history",
    "market_record",
    "mint_facts",
    "read_samples",
    "search",
    "top10_pct",
    "tokens",
    "unique_traders",
]
