#!/usr/bin/env python3
"""GTASP10 live logo renderer.

Fills the coin-stack faces of the 'heist bag' template with the logos of the
current GTASP10 top 10 (index weight order). Read-only w.r.t. index data;
only network access is public DexScreener GET requests. No wallets, no posting.

Sources (first usable wins):
  1. index members  (/var/lib/coin/index-data/index/out/<latest>.json, by weight)
  2. fallback: pool of sane candidates (data/candidates.json) + static GTA list,
     ranked by live DexScreener market cap (liquidity >= MIN_LIQ)
  3. static list as-is
"""

import glob
import io
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

TEMPLATE = os.environ.get("GTASP10_LOGO_TEMPLATE", "/usr/local/share/gtasp10/logo_template.jpg")
INDEX_GLOB = os.environ.get("GTASP10_INDEX_GLOB", "/var/lib/coin/index-data/index/out/*T*.json")
CANDIDATES = os.environ.get("GTASP10_CANDIDATES", "/var/www/gtasp10/data/candidates.json")
OUT_DIR = os.environ.get("GTASP10_LOGO_OUT", "/var/www/gtasp10")
CACHE = os.environ.get("GTASP10_LOGO_CACHE", "/var/cache/gtasp10-logo")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
UA = {"User-Agent": "gtasp10-logo/1.0", "Accept": "*/*"}
MIN_LIQ = 10000.0
SS = 4  # supersampling for faces

STATIC_TOP = [
    "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz",
    "nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump",
    "DKYcjobF7HPtL9RyQBRdeRQ2iWvizpfbgWwPWNXdpump",
    "AKotzk1dhcNangAJBtvNKtT9bhbSVZc2mMhRFgkFpump",
    "7KBFymfGAe8MmKEuNersoM59TvpiHzZ76jP7rSLrpump",
    "HsZXb9rppRQarZHHCvuLkKP7sAKPMCwrarf5KTTcpump",
    "HZbiEpF2oM658EpjNRRqxharz5L9Ddm8akpSH2R5pump",
    "BsbsB3WLq7vbY5En3MBCAsTrcwaCxNKY2Mp5pGuLpump",
    "HCNhQCu5nrmWhSE3mo7fRU9eGiGLmi2fnE8omgLpump",
    "9HFUEab7sompLDPTAaTGkryMNGbtBaFMhHMVpJEBpump",
]
# Mints whose DexScreener image is a placeholder -> draw text instead.
TEXT_OVERRIDE = {"4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz": "GTA VI"}

# Grey top faces detected in the template (centre x/y, half-axes a/b), listed in
# prominence order: front row from the centre outwards, then back row.
# The last face gets the gold '10' emblem.
FACES = [
    (539.8, 326.7, 40.6, 26.2),  # front centre (pink)  -> #1
    (441.0, 330.8, 40.4, 26.0),  # front (blue)          -> #2
    (636.4, 345.5, 40.4, 26.0),  # front (gold)          -> #3
    (357.2, 374.6, 40.0, 26.4),  # front (green)         -> #4
    (743.9, 359.5, 40.0, 25.4),  # front right (blue)    -> #5
    (274.8, 327.0, 39.4, 24.8),  # front left (gold)     -> #6
    (527.7, 225.1, 40.0, 24.6),  # back centre (purple)  -> #7
    (429.8, 238.3, 40.0, 25.0),  # back (green)          -> #8
    (626.6, 246.5, 41.0, 25.8),  # back (gold)           -> #9
    (335.5, 270.7, 40.0, 25.8),  # back (purple)         -> #10
    (720.1, 280.6, 40.0, 25.0),  # back right (gold)     -> '10' emblem
]


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# Hardening (audit #271 M5, D39): https only, host allowlist (also on redirects), size and
# pixel caps. Coin images come from third parties via DexScreener; never trust them.
ALLOWED_HOSTS = frozenset(
    {
        "api.dexscreener.com",
        "cdn.dexscreener.com",
        "dd.dexscreener.com",
        "ipfs.io",
        "gateway.pinata.cloud",
        "cf-ipfs.com",
        "dweb.link",
    }
)
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per response
MAX_PIXELS = 4096 * 4096  # decompression-bomb guard
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow raises DecompressionBombError above 2x this


def _check_url(url):
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or host not in ALLOWED_HOSTS or u.port not in (None, 443):
        raise ValueError(f"blocked URL (scheme/host not allowed): {u.scheme}://{host}")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(
    _SafeRedirect, urllib.request.HTTPSHandler, urllib.request.HTTPErrorProcessor
)


def http_get(url, timeout=20):
    req = urllib.request.Request(_check_url(url), headers=UA)
    with _OPENER.open(req, timeout=timeout) as r:
        n = r.headers.get("Content-Length")
        if n and n.isdigit() and int(n) > MAX_BYTES:
            raise ValueError(f"response too large: {n} bytes")
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("response too large")
    return data


def open_image(data):
    """Decode an untrusted image with size checks before and after decoding."""
    img = Image.open(io.BytesIO(data))
    w, h = img.size
    if w * h > MAX_PIXELS or w <= 0 or h <= 0:
        raise ValueError(f"image too large: {w}x{h}")
    if img.format not in ("PNG", "JPEG", "WEBP", "GIF"):
        raise ValueError(f"image format not allowed: {img.format}")
    img.load()
    return img


def dex_pairs(mints):
    """mint -> best (highest-liquidity) pair where it is the base token."""
    best = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i : i + 30]
        try:
            data = json.loads(
                http_get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk))
            )
        except Exception as e:
            log("dexscreener batch failed:", e)
            continue
        for p in data if isinstance(data, list) else data.get("pairs") or []:
            m = (p.get("baseToken") or {}).get("address")
            if m not in chunk:
                continue
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            if m not in best or liq > best[m]["_liq"]:
                p["_liq"] = liq
                best[m] = p
        time.sleep(0.3)
    return best


def index_members():
    files = sorted(glob.glob(INDEX_GLOB))
    for f in reversed(files):
        try:
            d = load_json(f)
        except Exception:
            continue
        mem = d.get("members") or []
        out = []
        for m in mem:
            if isinstance(m, str):
                out.append((m, 0.0, None))
            elif isinstance(m, dict) and m.get("mint"):
                w = m.get("weight", m.get("w", m.get("weight_pct", 0))) or 0
                out.append((m["mint"], float(w), m.get("ticker") or m.get("symbol")))
        out.sort(key=lambda x: -x[1])
        return d.get("as_of"), out
    return None, []


def candidate_pool():
    try:
        c = load_json(CANDIDATES).get("candidates") or []
    except Exception as e:
        log("candidates unreadable:", e)
        return []
    pool = []
    for x in c:
        mc, liq, vol = x.get("mc") or 0, x.get("liq") or 0, x.get("vol24h") or 0
        # drop obviously spoofed/dead entries (huge mc with ~0 volume, no liquidity)
        if mc >= 50000 and liq >= MIN_LIQ and vol >= 5000 and liq <= mc:
            pool.append(x["mint"])
    return pool


def pick_coins():
    as_of, mem = index_members()
    coins, source = [], None
    if mem:
        coins = [{"mint": m, "ticker": t, "weight": w} for m, w, t in mem[:10]]
        source = "index"
    if len(coins) < 10:
        have = {c["mint"] for c in coins}
        pool = [m for m in dict.fromkeys(candidate_pool() + STATIC_TOP) if m not in have]
        pairs = dex_pairs(pool)
        ranked = []
        for m in pool:
            p = pairs.get(m)
            if not p or p["_liq"] < MIN_LIQ:
                continue
            mc = float(p.get("marketCap") or p.get("fdv") or 0)
            ranked.append((mc, m, (p.get("baseToken") or {}).get("symbol")))
        ranked.sort(reverse=True)
        if ranked:
            for mc, m, t in ranked[: 10 - len(coins)]:
                coins.append({"mint": m, "ticker": t, "mcap_usd": round(mc)})
            source = (source + "+" if source else "") + "fallback:dexscreener_mcap"
        elif not coins:
            coins = [{"mint": m, "ticker": None} for m in STATIC_TOP]
            source = "fallback:static_list"
    return as_of, source, coins[:10]


def logo_for(mint):
    """Return (PIL image or None, symbol)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, mint + ".png")
    meta_path = os.path.join(CACHE, mint + ".json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            meta = load_json(meta_path)
        except Exception:
            meta = {}
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400
    if not fresh:
        try:
            d = json.loads(http_get("https://api.dexscreener.com/latest/dex/tokens/" + mint))
            pairs = [
                p for p in d.get("pairs") or [] if (p.get("baseToken") or {}).get("address") == mint
            ]
            pairs.sort(key=lambda p: -float((p.get("liquidity") or {}).get("usd") or 0))
            url = next(
                (p["info"]["imageUrl"] for p in pairs if (p.get("info") or {}).get("imageUrl")),
                None,
            )
            if pairs:
                meta["symbol"] = pairs[0]["baseToken"].get("symbol")
            if url:
                u = urllib.parse.urlsplit(url)
                url = urllib.parse.urlunsplit(
                    (u.scheme, u.netloc, u.path, "width=800&height=800&quality=95&format=auto", "")
                )
                img = open_image(http_get(url))
                img.convert("RGBA").save(path + ".tmp", "PNG")
                os.replace(path + ".tmp", path)
                meta["image"] = url
            with open(meta_path, "w") as fh:
                json.dump(meta, fh)
        except Exception as e:
            log("logo fetch failed", mint, e)
    img = None
    if os.path.exists(path):
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            img = None
    return img, meta.get("symbol")


def square(img):
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    bg = Image.new("RGBA", img.size, (20, 20, 24, 255))
    bg.alpha_composite(img)
    return bg.convert("RGB")


def fit_text(draw, text, box_w, box_h, start):
    size = start
    while size > 8:
        f = ImageFont.truetype(FONT, size)
        lft, t, r, b = draw.multiline_textbbox(
            (0, 0), text, font=f, align="center", spacing=size // 8
        )
        if r - lft <= box_w and b - t <= box_h:
            return f, (lft, t, r, b)
        size -= 2
    f = ImageFont.truetype(FONT, 8)
    return f, draw.multiline_textbbox((0, 0), text, font=f, align="center")


def text_face(text, n=800, vice=False):
    im = Image.new("RGB", (n, n))
    d = ImageDraw.Draw(im)
    for y in range(n):  # dark radial-ish vertical gradient
        k = y / n
        col = (
            (int(40 + 50 * k), int(18 + 10 * k), int(60 + 30 * k))
            if vice
            else (int(28 + 20 * k),) * 3
        )
        d.line([(0, y), (n, y)], fill=col)
    text = text.replace(" ", "\n") if len(text) > 5 else text
    f, (lft, t, r, b) = fit_text(d, text, int(n * 0.72), int(n * 0.6), int(n * 0.45))
    x, y = (n - (r - lft)) / 2 - lft, (n - (b - t)) / 2 - t
    fill = (255, 120, 200) if vice else (255, 255, 255)
    d.multiline_text(
        (x + 10, y + 12), text, font=f, fill=(0, 0, 0), align="center", spacing=f.size // 8
    )
    d.multiline_text(
        (x, y),
        text,
        font=f,
        fill=fill,
        align="center",
        spacing=f.size // 8,
        stroke_width=max(2, f.size // 18),
        stroke_fill=(255, 255, 255) if vice else (0, 0, 0),
    )
    return im


def gold_emblem(n=800):
    im = Image.new("RGB", (n, n))
    d = ImageDraw.Draw(im)
    for y in range(n):
        k = y / n
        d.line([(0, y), (n, y)], fill=(int(250 - 90 * k), int(205 - 85 * k), int(90 - 50 * k)))
    c = n // 2
    for r, col, w in ((int(n * 0.46), (120, 80, 20), 18), (int(n * 0.40), (255, 230, 150), 8)):
        d.ellipse([c - r, c - r, c + r, c + r], outline=col, width=w)
    f, (lft, t, r, b) = fit_text(d, "10", int(n * 0.62), int(n * 0.55), int(n * 0.6))
    x, y = (n - (r - lft)) / 2 - lft, (n - (b - t)) / 2 - t
    d.text((x + 8, y + 8), "10", font=f, fill=(255, 240, 180))  # engraved: light lower-right
    d.text((x - 6, y - 6), "10", font=f, fill=(110, 70, 15))  # dark upper-left
    d.text((x, y), "10", font=f, fill=(205, 150, 45))
    return im


def paste_face(base, face_img, cx, cy, a, b):
    """Print face_img onto the ellipse (cx,cy,a,b) with rim + shading."""
    W, H = int(math.ceil(2 * a)) + 4, int(math.ceil(2 * b)) + 4
    x0, y0 = int(round(cx - W / 2)), int(round(cy - H / 2))
    sw, sh = W * SS, H * SS
    ex = [(W / 2 - a) * SS, (H / 2 - b) * SS, (W / 2 + a) * SS, (H / 2 + b) * SS]
    # logo: circle-crop then squash vertically (perspective of a tilted coin)
    lg = face_img.resize((int(2 * a * SS), int(2 * a * SS)), Image.LANCZOS)
    lg = lg.resize((int(2 * a * SS), int(2 * b * SS)), Image.LANCZOS)
    layer = Image.new("RGB", (sw, sh))
    layer.paste(lg, (int(ex[0]), int(ex[1])))
    # shading: light top-left, darker bottom
    shade = Image.new("L", (sw, sh), 0)
    sd = ImageDraw.Draw(shade)
    for yy in range(sh):
        sd.line([(0, yy), (sw, yy)], fill=int(70 * yy / sh))
    layer = Image.composite(Image.new("RGB", (sw, sh)), layer, shade)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).ellipse(ex, fill=255)
    # rim: thin highlight arc on top, dark inner edge
    rim = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.ellipse(ex, outline=(0, 0, 0, 170), width=int(2.2 * SS))
    rd.arc(
        [ex[0] + SS, ex[1] + SS, ex[2] - SS, ex[3] - SS],
        195,
        335,
        fill=(255, 255, 255, 150),
        width=int(1.3 * SS),
    )
    rd.arc(
        [ex[0] + SS, ex[1] + SS, ex[2] - SS, ex[3] - SS],
        20,
        160,
        fill=(0, 0, 0, 90),
        width=int(1.6 * SS),
    )
    gloss = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse(
        [
            ex[0] + 0.15 * (ex[2] - ex[0]),
            ex[1] + 0.06 * (ex[3] - ex[1]),
            ex[0] + 0.6 * (ex[2] - ex[0]),
            ex[1] + 0.4 * (ex[3] - ex[1]),
        ],
        fill=(255, 255, 255, 38),
    )
    gloss = gloss.filter(ImageFilter.GaussianBlur(4 * SS))
    face = layer.convert("RGBA")
    face.alpha_composite(gloss)
    face.alpha_composite(rim)
    face.putalpha(ImageChops.multiply(face.getchannel("A"), mask))
    face = face.resize((W, H), Image.LANCZOS)
    base.alpha_composite(face, (x0, y0))


def atomic_save(img, path, **kw):
    tmp = path + ".tmp"
    img.save(tmp, "PNG", optimize=True, **kw)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main():
    as_of, source, coins = pick_coins()
    log("source:", source, "coins:", len(coins))
    base = Image.open(TEMPLATE).convert("RGBA")
    used = []
    for i, face in enumerate(FACES):
        if i == len(FACES) - 1 or i >= len(coins):
            paste_face(base, gold_emblem(), *face)
            continue
        c = coins[i]
        m = c["mint"]
        img, sym = logo_for(m)
        ticker = c.get("ticker") or sym or m[:4]
        if m in TEXT_OVERRIDE:
            art, kind = text_face(TEXT_OVERRIDE[m], vice=True), "text_override"
        elif img is not None:
            art, kind = square(img), "logo"
        else:
            art, kind = text_face(("$" + ticker)[:8]), "ticker_text"
        paste_face(base, art, *face)
        used.append(
            {
                "rank": i + 1,
                "mint": m,
                "ticker": ticker,
                "face": kind,
                **{k: c[k] for k in ("weight", "mcap_usd") if k in c},
            }
        )
    out = base.convert("RGB")
    os.makedirs(OUT_DIR, exist_ok=True)
    atomic_save(out, os.path.join(OUT_DIR, "logo.png"))
    atomic_save(out.resize((400, 400), Image.LANCZOS), os.path.join(OUT_DIR, "logo-400.png"))
    meta = {
        "as_of": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "index_as_of": as_of,
        "source": source,
        "coins": used,
    }
    tmp = os.path.join(OUT_DIR, "logo.json.tmp")
    with open(tmp, "w") as fh:
        json.dump(meta, fh, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(OUT_DIR, "logo.json"))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
