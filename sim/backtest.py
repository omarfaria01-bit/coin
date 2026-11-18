"""Hourly backtest of the current GTA index rules.

Replays official hourly snapshots with the live filters and sqrt-mcap weights,
and (unless --no-ohlcv) extends the price path with public GeckoTerminal
hourly candles for the coins that pass the latest snapshot. No API key.

Writes web/data/backtest.json. Floats are index prices, not reward payouts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from index.filters import (  # noqa: E402
    Metrics,
    candidate_status,
    first_failed_filter,
    log_score,
)
from index.params import IndexParams, Overrides  # noqa: E402
from index.select import weights_bps  # noqa: E402

LAMPORTS_NOTE = "Prices are public pool closes. This is a simulation, not a live result."
SOL_MINT = "So11111111111111111111111111111111111111112"
_UA = {"accept": "application/json", "user-agent": "gtasp10-backtest/0.1"}


def load_params() -> tuple[IndexParams, Overrides]:
    params = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
    raw = json.loads((ROOT / "index" / "overrides.json").read_text())
    overrides = Overrides.model_validate(raw)
    return params, overrides


def metrics_from_mapping(raw: Mapping[str, object]) -> Metrics:
    """Build Metrics from a published member.metrics object. Unknown keys are dropped."""
    allowed = set(Metrics.__dataclass_fields__)
    data = {key: raw[key] for key in allowed if key in raw}
    extensions = data.get("extensions")
    if isinstance(extensions, list):
        data["extensions"] = tuple(extensions)
    sources = data.get("sources")
    if isinstance(sources, dict):
        data["sources"] = dict(sources)
    return Metrics(**data)  # type: ignore[arg-type]


def passing_members(
    doc: Mapping[str, object], params: IndexParams, overrides: Overrides
) -> list[Metrics]:
    """Members of one official file that still pass the current filters and score."""
    out: list[Metrics] = []
    for item in doc.get("members") or []:  # type: ignore[union-attr]
        if not isinstance(item, Mapping):
            continue
        raw = dict(item.get("metrics") or {})
        raw.setdefault("mint", item.get("mint"))
        raw.setdefault("ticker", item.get("ticker") or "")
        if not isinstance(raw.get("mint"), str):
            continue
        metrics = metrics_from_mapping(raw)
        if candidate_status(metrics, params, overrides) is not None:
            continue
        if first_failed_filter(metrics, params) is not None:
            continue
        if log_score(metrics, params) is None:
            continue
        out.append(metrics)
    return out


def weight_from_mc(pairs: Sequence[tuple[str, float]], params: IndexParams) -> dict[str, int]:
    """Integer bps from the shipped sqrt-mcap rule. `pairs` is (mint, market cap)."""
    ordered = sorted(pairs, key=lambda pair: (-pair[1], pair[0]))
    mints = [mint for mint, _mc in ordered]
    if not mints:
        return {}
    mc_volume = {mint: (mc, 1.0) for mint, mc in ordered}
    scored = dict.fromkeys(mints, 0.0)
    return weights_bps(mints, scored, params, mc_volume)


def portfolio_return(bps: Mapping[str, int], rets: Mapping[str, float]) -> float:
    total = sum(bps.values())
    if total <= 0:
        return 0.0
    return sum(bps[mint] / total * rets.get(mint, 0.0) for mint in bps)


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough drop as a fraction of the peak. 0 when the path never falls."""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class CoinPath:
    mint: str
    ticker: str
    pool_created: int | None
    anchor_mc: float
    anchor_px: float
    bars: dict[int, tuple[float, float]]  # hour unix -> (close usd, volume usd)

    def mcap(self, hour: int) -> float | None:
        bar = self.bars.get(hour)
        if bar is None or self.anchor_px <= 0 or bar[0] <= 0:
            return None
        return self.anchor_mc * bar[0] / self.anchor_px


def simulate(
    coins: Sequence[CoinPath],
    params: IndexParams,
    sol_bars: Mapping[int, float] | None = None,
    min_age_hours: float = 4.0,
) -> dict:
    """Hourly sqrt-mcap equity for coins that have a candle, volume and enough age.

    Membership is the set passed in (already filter-passing at the anchor snapshot).
    A coin is in an hour only when that hour has a positive close, positive volume,
    reconstructed market cap, and pool age of at least `min_age_hours`.
    """
    hours = sorted({hour for coin in coins for hour in coin.bars})
    if len(hours) < 2:
        return _empty("not enough hourly prices")
    index_eq = [1.0]
    equal_eq = [1.0]
    top_eq = [1.0]
    sol_level = 1.0
    sol_path: list[float] = [1.0] if sol_bars and hours[0] in sol_bars else []
    curve = [
        {
            "t": _iso(hours[0]),
            "index": 1.0,
            "equal_weight": 1.0,
            "top_coin": 1.0,
            "sol": 1.0 if sol_path else None,
        }
    ]
    rebalances = 0
    present: dict[str, int] = dict.fromkeys((c.mint for c in coins), 0)
    tickers = {c.mint: c.ticker for c in coins}
    top_mint = max(coins, key=lambda c: c.anchor_mc).mint if coins else ""
    age_cut = int(min_age_hours * 3600)

    for prev, nxt in zip(hours, hours[1:], strict=False):
        if nxt - prev != 3600:
            # A gap is not a rebalance. Carry the books flat across the missing hour.
            continue
        basket: list[tuple[str, float]] = []
        rets: dict[str, float] = {}
        for coin in coins:
            now = coin.bars.get(prev)
            later = coin.bars.get(nxt)
            if now is None or later is None or now[0] <= 0 or later[0] <= 0 or now[1] <= 0:
                continue
            if coin.pool_created is not None and prev < coin.pool_created + age_cut:
                continue
            mcap = coin.mcap(prev)
            if mcap is None or mcap <= 0 or not math.isfinite(mcap):
                continue
            basket.append((coin.mint, mcap))
            rets[coin.mint] = later[0] / now[0] - 1.0
            present[coin.mint] = present.get(coin.mint, 0) + 1
        if not basket:
            continue
        bps = weight_from_mc(basket, params)
        rebalances += 1
        step = portfolio_return(bps, rets)
        n = len(basket)
        equal_step = sum(rets[mint] for mint, _mc in basket) / n
        index_eq.append(index_eq[-1] * (1.0 + step))
        equal_eq.append(equal_eq[-1] * (1.0 + equal_step))
        top_eq.append(top_eq[-1] * (1.0 + rets.get(top_mint, 0.0)))
        sol_marked: float | None = None
        if (
            sol_bars
            and prev in sol_bars
            and nxt in sol_bars
            and sol_bars[prev] > 0
            and sol_bars[nxt] > 0
        ):
            sol_level *= sol_bars[nxt] / sol_bars[prev]
            sol_path.append(sol_level)
            sol_marked = sol_level
        curve.append(
            {
                "t": _iso(nxt),
                "index": round(index_eq[-1], 6),
                "equal_weight": round(equal_eq[-1], 6),
                "top_coin": round(top_eq[-1], 6),
                "sol": None if sol_marked is None else round(sol_marked, 6),
            }
        )

    included = [
        {"mint": mint, "ticker": tickers.get(mint, ""), "hours": present.get(mint, 0)}
        for mint in sorted(present, key=lambda m: (-present[m], m))
        if present.get(mint, 0) > 0
    ]
    return {
        "history": {
            "start": curve[0]["t"],
            "end": curve[-1]["t"],
            "hours": int((hours[-1] - hours[0]) / 3600) if hours else 0,
            "points": len(curve),
            "rebalances": rebalances,
        },
        "index": {"end": round(index_eq[-1], 6), "max_drawdown": round(max_drawdown(index_eq), 6)},
        "equal_weight": {
            "end": round(equal_eq[-1], 6),
            "max_drawdown": round(max_drawdown(equal_eq), 6),
        },
        "top_coin": {
            "mint": top_mint,
            "ticker": tickers.get(top_mint, ""),
            "end": round(top_eq[-1], 6),
            "max_drawdown": round(max_drawdown(top_eq), 6),
        },
        "sol": {
            "end": round(sol_path[-1], 6) if sol_path else None,
            "max_drawdown": round(max_drawdown(sol_path), 6) if len(sol_path) > 1 else None,
            "hours": max(0, len(sol_path) - 1),
        },
        "coins": included,
        "curve": curve,
    }


def published_replay(
    docs: Sequence[Mapping[str, object]], params: IndexParams, overrides: Overrides
) -> dict:
    """Forward market-cap returns on official hours, weights recomputed with today's rule."""
    usable = []
    for doc in docs:
        members = passing_members(doc, params, overrides)
        if not members:
            continue
        mc = {m.mint: float(m.mc_usd or 0.0) for m in members}
        for row in doc.get("excluded") or []:  # type: ignore[union-attr]
            if isinstance(row, Mapping) and isinstance(row.get("mc_usd"), int | float):
                mc.setdefault(str(row["mint"]), float(row["mc_usd"]))
        usable.append((str(doc.get("as_of")), members, mc))
    if len(usable) < 2:
        return {
            "hours": len(usable),
            "rebalances": 0,
            "index_end": 1.0,
            "note": "fewer than 2 official hours",
        }
    equity = 1.0
    rebalances = 0
    for (_as_of, members, mc), (_nxt, _nm, mc2) in zip(usable, usable[1:], strict=False):
        pairs = [(m.mint, mc[m.mint]) for m in members if mc.get(m.mint, 0) > 0]
        bps = weight_from_mc(pairs, params)
        rets = {}
        for mint, weight in bps.items():
            if weight <= 0 or mc.get(mint, 0) <= 0 or mc2.get(mint, 0) <= 0:
                continue
            rets[mint] = mc2[mint] / mc[mint] - 1.0
        equity *= 1.0 + portfolio_return(bps, rets)
        rebalances += 1
    return {
        "start": usable[0][0],
        "end": usable[-1][0],
        "hours_with_members": len(usable),
        "rebalances": rebalances,
        "index_end": round(equity, 6),
        "note": (
            "Full current filters on stored metrics, sqrt-mcap weights, "
            "market-cap change as the price."
        ),
    }


def _empty(reason: str) -> dict:
    return {
        "history": {"start": None, "end": None, "hours": 0, "points": 0, "rebalances": 0},
        "index": {"end": 1.0, "max_drawdown": 0.0},
        "equal_weight": {"end": 1.0, "max_drawdown": 0.0},
        "top_coin": {"mint": "", "ticker": "", "end": 1.0, "max_drawdown": 0.0},
        "sol": {"end": 1.0, "max_drawdown": 0.0},
        "coins": [],
        "curve": [],
        "note": reason,
    }


def load_official(directory: Path) -> list[dict]:
    docs = []
    for path in sorted(directory.glob("*.json")):
        if path.name == "emergency.json" or ".dryrun." in path.name:
            continue
        stem = path.name[:-5]
        if len(stem) != 13 or stem[10] != "T":
            continue
        doc = json.loads(path.read_text())
        if doc.get("dry_run"):
            continue
        docs.append(doc)
    docs.sort(key=lambda d: str(d.get("as_of") or ""))
    return docs


def _get_json(url: str) -> dict:
    last: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(url, headers=_UA)
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503) or attempt == 2:
                raise
            time.sleep(1.2 * (attempt + 1))
    else:
        if last:
            raise last
        raise ValueError("no response")
    if not isinstance(payload, dict):
        raise ValueError("unexpected payload")
    return payload


def _pool_for(mint: str) -> tuple[str, str, int | None]:
    """Highest-reserve pool address, ohlcv side ('base' or 'quote'), created unix."""
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/pools?page=1"
    data = _get_json(url)
    best: tuple[float, str, str, int | None] | None = None
    for pool in data.get("data") or []:
        if not isinstance(pool, Mapping):
            continue
        attr = pool.get("attributes") or {}
        rel = pool.get("relationships") or {}
        base = str(((rel.get("base_token") or {}).get("data") or {}).get("id") or "")
        quote = str(((rel.get("quote_token") or {}).get("data") or {}).get("id") or "")
        side = "base" if base.endswith(mint) else "quote" if quote.endswith(mint) else ""
        if not side:
            continue
        try:
            reserve = float(attr.get("reserve_in_usd") or 0)
        except (TypeError, ValueError):
            reserve = 0.0
        pid = str(pool.get("id") or "")
        addr = pid.split("_", 1)[1] if "_" in pid else ""
        if not addr:
            continue
        created = _parse_time(str(attr.get("pool_created_at") or ""))
        if best is None or reserve > best[0]:
            best = (reserve, addr, side, created)
    if best is None:
        raise ValueError(f"no pool for {mint}")
    return best[1], best[2], best[3]


def _parse_time(text: str) -> int | None:
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _ohlcv(addr: str, side: str) -> dict[int, tuple[float, float]]:
    url = (
        "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
        f"{addr}/ohlcv/hour?aggregate=1&limit=1000&currency=usd&token={side}"
    )
    data = _get_json(url)
    rows = ((data.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    out: dict[int, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        hour = int(row[0]) // 3600 * 3600
        close = float(row[4])
        volume = float(row[5])
        if close > 0 and math.isfinite(close):
            out[hour] = (close, volume if math.isfinite(volume) else 0.0)
    return out


def fetch_paths(
    members: Sequence[Metrics], pause: float
) -> tuple[list[CoinPath], dict[int, float], list[str]]:
    """Public hourly candles. Returns (coins, sol closes, caveats)."""
    coins: list[CoinPath] = []
    notes: list[str] = []
    for metrics in members:
        try:
            addr, side, created = _pool_for(metrics.mint)
            time.sleep(pause)
            bars = _ohlcv(addr, side)
            time.sleep(pause)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            notes.append(f"{metrics.ticker}: price history unavailable ({type(exc).__name__})")
            continue
        if not bars or not metrics.mc_usd or metrics.mc_usd <= 0:
            notes.append(f"{metrics.ticker}: no usable hourly candles")
            continue
        coins.append(
            CoinPath(
                mint=metrics.mint,
                ticker=metrics.ticker,
                pool_created=created,
                anchor_mc=float(metrics.mc_usd),
                anchor_px=0.0,  # filled once the snapshot hour is known
                bars=bars,
            )
        )
    sol, sol_note = fetch_sol(pause)
    if sol_note:
        notes.append(sol_note)
    return coins, sol, notes


def fetch_sol(pause: float) -> tuple[dict[int, float], str | None]:
    """Hourly SOL/USD. CoinGecko first; a deep SOL/USDC pool if that is down."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/solana/market_chart?vs_currency=usd&days=90"
        data = _get_json(url)
        sol: dict[int, float] = {}
        for row in data.get("prices") or []:
            if not isinstance(row, list) or len(row) < 2:
                continue
            hour = int(row[0] / 1000) // 3600 * 3600
            px = float(row[1])
            if px > 0 and math.isfinite(px):
                sol[hour] = px
        if len(sol) > 24:
            return sol, "SOL line is the CoinGecko SOL/USD hourly price, rebased to 1."
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        pass
    time.sleep(pause)
    try:
        url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{SOL_MINT}/pools?page=1"
        data = _get_json(url)
        best: tuple[float, str, str] | None = None
        for pool in data.get("data") or []:
            if not isinstance(pool, Mapping):
                continue
            attr = pool.get("attributes") or {}
            name = str(attr.get("name") or "")
            parts = [part.strip() for part in name.split("/")]
            if sorted(parts) not in (["SOL", "USDC"], ["SOL", "USDT"], ["SOL", "USDG"]):
                continue
            try:
                reserve = float(attr.get("reserve_in_usd") or 0)
            except (TypeError, ValueError):
                reserve = 0.0
            pid = str(pool.get("id") or "")
            addr = pid.split("_", 1)[1] if "_" in pid else ""
            side = "base" if parts and parts[0] == "SOL" else "quote"
            if addr and (best is None or reserve > best[0]):
                best = (reserve, addr, side)
        if best is None:
            return {}, "SOL price history was not available."
        time.sleep(pause)
        sol = {hour: close for hour, (close, _vol) in _ohlcv(best[1], best[2]).items()}
        if len(sol) < 24:
            return {}, "SOL price history was too short to plot."
        return sol, "SOL line is the deepest SOL/USDC pool on GeckoTerminal, rebased to 1."
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return {}, "SOL price history was not available."


def _with_anchor(coins: Sequence[CoinPath], anchor_hour: int) -> list[CoinPath]:
    out = []
    for coin in coins:
        px = coin.bars.get(anchor_hour, (0.0, 0.0))[0]
        if px <= 0:
            # nearest candle within 3 hours
            near = [h for h in coin.bars if abs(h - anchor_hour) <= 3 * 3600]
            if not near:
                continue
            px = coin.bars[min(near, key=lambda h: abs(h - anchor_hour))][0]
        if px <= 0:
            continue
        out.append(
            CoinPath(
                coin.mint,
                coin.ticker,
                coin.pool_created,
                coin.anchor_mc,
                px,
                coin.bars,
            )
        )
    return out


def build_report(
    index_dir: Path, *, ohlcv: bool = True, pause: float = 0.35, generated_at: str | None = None
) -> dict:
    params, overrides = load_params()
    docs = load_official(index_dir)
    latest_members: list[Metrics] = []
    anchor = ""
    for doc in docs:
        found = passing_members(doc, params, overrides)
        if found:
            latest_members = found
            anchor = str(doc.get("as_of") or "")
    caveats = [
        "Past simulated performance. It is not a promise of future results.",
        "The price history is short, and several hours of the live index are still missing.",
        (
            "The basket is the coins that pass the current filters on the latest official "
            "snapshot, replayed backward. Coins that failed the filters are not added later. "
            "That is survivorship of today's basket."
        ),
        (
            "Holder concentration, launch bundle, authorities, trader count and the $50,000 "
            "liquidity floor are applied on the official snapshots. They are not re-checked "
            "on earlier hours, because the public candles do not carry those fields."
        ),
        (
            "Each earlier hour still requires a positive close, positive volume and a pool "
            "at least 4 hours old. Weights are recomputed every hour from the square root "
            "of reconstructed market cap (18% cap, 5% floor)."
        ),
        (
            "Market cap is the published market cap scaled by the public price. Supply is "
            "assumed constant. Hourly closes ignore trading costs and slippage."
        ),
        LAMPORTS_NOTE,
    ]
    report: dict = {
        "generated_at": generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rules": {
            "weights": params.weights.mode,
            "cap_pct": int(params.weights.cap_pct),
            "floor_pct": int(params.weights.floor_pct),
            "rebalance_hours": int(params.rebalance_hours),
        },
        "anchor_as_of": anchor,
        "published_replay": published_replay(docs, params, overrides),
        "caveats": caveats,
    }
    if not ohlcv or not latest_members or not anchor:
        sim = _empty("no official basket" if not latest_members else "ohlcv skipped")
        sim["coins"] = [{"mint": m.mint, "ticker": m.ticker, "hours": 0} for m in latest_members]
        report.update(sim)
        report["caveats"] = caveats + ["No public price history was loaded for this file."]
        return report
    anchor_dt = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
    anchor_hour = int(anchor_dt.timestamp()) // 3600 * 3600
    raw, sol, notes = fetch_paths(latest_members, pause)
    anchored = _with_anchor(raw, anchor_hour)
    min_age = float(params.filters.min_age_hours)
    sim = simulate(anchored, params, sol or None, min_age_hours=min_age)
    report.update(sim)
    if notes:
        report["caveats"] = caveats + notes
    if not sol:
        report["sol"] = {
            "end": None,
            "max_drawdown": None,
            "note": "SOL candles were not available",
        }
    report["coins_in_anchor"] = len(latest_members)
    return report


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write web/data/backtest.json")
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "web" / "data" / "backtest.json")
    parser.add_argument("--no-ohlcv", action="store_true")
    parser.add_argument("--pause", type=float, default=0.35)
    args = parser.parse_args(argv)
    report = build_report(args.index_dir, ohlcv=not args.no_ohlcv, pause=args.pause)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")
    hist = report["history"]
    print(
        f"wrote {args.out} hours={hist['hours']} rebalances={hist['rebalances']} "
        f"index_end={report['index']['end']} max_dd={report['index']['max_drawdown']} "
        f"coins={len(report['coins'])}"
    )


if __name__ == "__main__":
    main()
