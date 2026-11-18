"""Read-only Helius RPC, DAS and Parsed Events, plus DexScreener liquidity.

The API key is read from the environment by the CLI. This module never logs the
request URL. Free-plan pacing (2026-11-17 rate-limit docs): RPC 10 req/s,
DAS and Parsed Events 2 req/s. DexScreener `/tokens/v1` is 300 req/min and is
used only for liquidity, and for price or market cap when DAS has no price.
`/latest/dex/search` is not called. No transaction is signed or sent.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# Free plan, https://www.helius.dev/docs/billing/rate-limits (2026-11-17).
# DAS and Parsed Events share 2 req/s. RPC is 10 req/s. History pages hold
# at most 100 txs and cost 10 credits; DAS costs 10 credits per call.
# DexScreener /tokens/v1 is 300 requests/minute, batches of 30.
RPC_MIN_INTERVAL_S = 0.1
DAS_MIN_INTERVAL_S = 0.5
DEX_MIN_INTERVAL_S = 0.25
DEX_BATCH = 30
HISTORY_PAGE_LIMIT = 100

Transport = Callable[[str, str, dict | None], tuple[int, object]]
_HOSTS = frozenset({"mainnet.helius-rpc.com", "api.dexscreener.com"})
_RETRY = frozenset({0, 408, 429, 500, 502, 503, 504})
_DAS_METHODS = frozenset({"getAsset", "getAssetBatch"})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def http_transport(
    method: str, url: str, body: dict | None, timeout: float = 30.0
) -> tuple[int, object]:
    """One HTTP call. Redirects are refused. The URL is never put in an exception."""
    host = urllib.parse.urlparse(url).hostname
    if host not in _HOSTS:
        raise ValueError("refusing unexpected host")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "coin-index-read/1"},
        method=method,
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None
    try:
        return status, json.loads(raw.decode())
    except (UnicodeError, json.JSONDecodeError):
        return status, None


@dataclass
class _Pace:
    interval: float
    sleep: Callable[[float], None]
    clock: Callable[[], float]
    _next: float = 0.0

    def wait(self) -> None:
        now = self.clock()
        if self.interval and now < self._next:
            self.sleep(self._next - now)
            now = self.clock()
        self._next = now + self.interval


class HeliusClient:
    """Mainnet reads only. `transport` is injected in tests so they make no network calls."""

    def __init__(
        self,
        api_key: str,
        transport: Transport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
        rpc_interval: float = RPC_MIN_INTERVAL_S,
        das_interval: float = DAS_MIN_INTERVAL_S,
        dex_interval: float = DEX_MIN_INTERVAL_S,
        max_history_pages: int = 30,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("HELIUS_API_KEY is empty")
        self._key = api_key.strip()
        self._transport = transport or http_transport
        self._sleep = sleep
        self._rng = rng
        self._rpc_pace = _Pace(rpc_interval, sleep, clock)
        self._das_pace = _Pace(das_interval, sleep, clock)
        self._dex_pace = _Pace(dex_interval, sleep, clock)
        self.max_history_pages = max_history_pages
        self.requests = {"rpc": 0, "das": 0, "parsed": 0, "dex": 0}

    def __repr__(self) -> str:
        return "HeliusClient(api_key=REDACTED)"

    def rpc(self, method: str, params: list[object] | dict[str, object]) -> object:
        kind = "das" if method in _DAS_METHODS else "rpc"
        payload = self._send(
            "POST",
            f"https://mainnet.helius-rpc.com/?api-key={self._key}",
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            self._das_pace if kind == "das" else self._rpc_pace,
            kind,
        )
        if not isinstance(payload, dict) or payload.get("error"):
            raise RuntimeError(f"helius {method} failed")
        return payload.get("result")

    def history(
        self,
        address: str,
        *,
        start: int | None = None,
        end: int | None = None,
        sort: str = "desc",
        max_pages: int | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        stop_on_cached: set[str] | None = None,
    ) -> tuple[list[dict[str, object]], bool]:
        """Parsed history. The bool is True when the page cap stopped the walk early."""
        token: str | None = None
        out: list[dict[str, object]] = []
        pages = max_pages if max_pages is not None else self.max_history_pages
        for _ in range(pages):
            body: dict[str, object] = {
                "address": address,
                "limit": limit,
                "sortOrder": sort,
                "status": "succeeded",
                "commitment": "confirmed",
                "rawTransaction": "none",
            }
            if token:
                body["paginationToken"] = token
            window: dict[str, int] = {}
            if start is not None:
                window["gte"] = start
            if end is not None:
                window["lt"] = end
            if window:
                body["time"] = window
            payload = self._send(
                "POST",
                f"https://mainnet.helius-rpc.com/v1/parsed-events/transaction-history?api-key={self._key}",
                body,
                self._das_pace,
                "parsed",
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise RuntimeError("helius history failed")
            page_rows = [row for row in payload["data"] if isinstance(row, dict)]
            out.extend(page_rows)
            if stop_on_cached is not None and page_rows:
                oldest_sig = page_rows[-1].get("signature")
                if isinstance(oldest_sig, str) and oldest_sig in stop_on_cached:
                    return out, False
            nxt = payload.get("paginationToken")
            if not isinstance(nxt, str) or not nxt:
                return out, False
            token = nxt
        return out, True

    def pairs(self, mints: Sequence[str]) -> list[Mapping[str, object]]:
        """DexScreener `/tokens/v1/solana/{mints}` only. Never the search endpoint."""
        found: list[Mapping[str, object]] = []
        for offset in range(0, len(mints), DEX_BATCH):
            chunk = ",".join(mints[offset : offset + DEX_BATCH])
            payload = self._send(
                "GET",
                f"https://api.dexscreener.com/tokens/v1/solana/{chunk}",
                None,
                self._dex_pace,
                "dex",
            )
            if not isinstance(payload, list):
                raise RuntimeError("dexscreener tokens failed")
            found.extend(row for row in payload if isinstance(row, Mapping))
        return found

    def _send(
        self,
        method: str,
        url: str,
        body: dict[str, object] | None,
        pace: _Pace,
        kind: str,
    ) -> object:
        delay = 1.0
        for attempt in range(1, 6):
            pace.wait()
            try:
                status, payload = self._transport(method, url, body)
            except Exception as exc:  # a transport must not leak the URL into our error
                status, payload = 0, None
                _ = type(exc).__name__
            self.requests[kind] += 1
            if status == 200 and payload is not None:
                return payload
            if status not in _RETRY or attempt == 5:
                raise RuntimeError(f"{kind} http {status}")
            self._sleep(delay * (0.75 + 0.5 * self._rng()))
            delay = min(delay * 2, 30.0)
        raise RuntimeError(f"{kind} http failed")
