import json
import math
import os
import subprocess  # nosec B404 - fixed ffmpeg argv, no untrusted input
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, DUR = 1280, 720, 30, 15.0
N = int(FPS * DUR)
G = "/usr/share/fonts/truetype/google-fonts/"
ANTON = G + "ofl/anton/Anton-Regular.ttf"
ARCH = [
    G + "ofl/archivoblack/" + f for f in os.listdir(G + "ofl/archivoblack") if f.endswith(".ttf")
][0]
POP = G + "Poppins-Bold.ttf"
POPM = G + "Poppins-Medium.ttf"


def F(p, s):
    return ImageFont.truetype(p, s)


PINK, HOT, ORANGE, YEL, CYAN, WHITE = (
    (255, 60, 172),
    (255, 45, 120),
    (255, 140, 60),
    (255, 209, 102),
    (70, 230, 255),
    (255, 255, 255),
)


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def back(t):
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def win(t, a, b, fi=0.35, fo=0.35):
    if t < a or t > b:
        return 0.0
    return min(ease((t - a) / fi), 1.0 if b - t > fo else ease((b - t) / fo))


# data
with open(sys.argv[1]) as fh:
    d = json.load(fh)
mem = sorted(d["members"], key=lambda m: -m["weight_bps"])
seen = {}
bars = []
for m in mem:
    t = m.get("ticker") or m["mint"][:4]
    seen[t] = seen.get(t, 0) + 1
    if seen[t] > 1:
        t = f"{t} ·{m['mint'][:4]}"
    bars.append((t, m["weight_bps"] / 100))

bg0 = Image.open(sys.argv[2]).convert("RGB")
logo = Image.open(sys.argv[3]).convert("RGBA")
BG = bg0.resize((int(W * 1.25), int(H * 1.25)), Image.LANCZOS)


def background(t):
    z = 1.0 + 0.2 * (t / DUR)
    w, h = int(W * 1.25 / z * 1.0), int(H * 1.25 / z * 1.0)
    w = max(W, int(BG.width / (1 + 0.2 * t / DUR)))
    h = int(w * H / W)
    x = (BG.width - w) // 2 + int(20 * math.sin(t * 0.3))
    y = (BG.height - h) // 2
    return BG.crop((x, y, x + w, y + h)).resize((W, H), Image.BILINEAR)


def overlay(img, a):
    ov = Image.new("RGB", (W, H), (12, 4, 24))
    return Image.blend(img, ov, a)


def text_layer(draw_fn):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(lay))
    return lay


def glow(lay, r=14, k=1.0):
    g = lay.filter(ImageFilter.GaussianBlur(r))
    if k != 1.0:
        a = g.getchannel("A").point(lambda v: min(255, int(v * k)))
        g.putalpha(a)
    return g


def grad_text(txt, font, c1, c2, cx, cy, scale=1.0, alpha=1.0):
    tmp = Image.new("L", (W, H), 0)
    dd = ImageDraw.Draw(tmp)
    bb = dd.textbbox((0, 0), txt, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    dd.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]), txt, font=font, fill=255)
    if scale != 1.0:
        tmp = tmp.resize((int(W * scale), int(H * scale)), Image.BICUBIC)
        c = Image.new("L", (W, H), 0)
        c.paste(
            tmp,
            (
                int((W - tmp.width) / 2 + (cx - W / 2) * (1 - scale)),
                int((H - tmp.height) / 2 + (cy - H / 2) * (1 - scale)),
            ),
        )
        tmp = c
    gr = Image.new("RGBA", (W, H))
    gd = ImageDraw.Draw(gr)
    for x in range(0, W, 4):
        f = x / W
        col = tuple(int(c1[i] + (c2[i] - c1[i]) * f) for i in range(3))
        gd.rectangle([x, 0, x + 4, H], fill=col + (255,))
    mask = tmp.point(lambda v: int(v * alpha))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(gr, (0, 0), mask)
    return out


def put(img, lay):
    img.paste(lay, (0, 0), lay)
    return img


def center_text(dr, txt, font, cy, fill, cx=W / 2):
    bb = dr.textbbox((0, 0), txt, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    dr.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]), txt, font=font, fill=fill)


fT = F(ANTON, 200)
fSub = F(POP, 34)
fH = F(ANTON, 66)
fS = F(POPM, 24)
fB = F(POP, 26)
fBig = F(ANTON, 130)
fL = F(ARCH, 34)
fURL = F(ANTON, 84)
fSmall = F(POPM, 20)


def frame(i):
    t = i / FPS
    img = background(t)
    # darkness per scene
    dk = (
        0.30
        + 0.38 * win(t, 3.0, 8.2, 0.5, 0.5)
        + 0.32 * win(t, 8.0, 12.2, 0.4, 0.4)
        + 0.25 * win(t, 12.0, 15.1, 0.4, 0.1)
    )
    img = overlay(img, min(dk, 0.78)).convert("RGBA")
    # S1 title
    a1 = win(t, 0.0, 3.3, 0.6, 0.45)
    if a1 > 0:
        s = 0.86 + 0.14 * back((t - 0.0) / 0.9)
        tl = grad_text("GTASP10", fT, HOT, YEL, W / 2, H / 2 - 40, s, a1)
        img = put(img, glow(tl, 22, 1.6))
        img = put(img, tl)
        a = a1 * ease((t - 0.7) / 0.5)
        if a > 0:
            dy = 20 * (1 - ease((t - 0.7) / 0.5))
            lay = text_layer(
                lambda d: center_text(
                    d,
                    "THE GTA 6 MEMECOIN INDEX  ·  SOLANA",
                    fSub,
                    H / 2 + 95 + dy,
                    CYAN + (int(255 * a),),
                )
            )
            img = put(img, glow(lay, 10))
            img = put(img, lay)
    # S2 bars
    a2 = win(t, 3.1, 8.2, 0.4, 0.45)
    if a2 > 0:
        lay = text_layer(
            lambda d: (
                center_text(d, "TOP 10 GTA 6 COINS", fH, 78, WHITE + (int(255 * a2),)),
                center_text(
                    d,
                    "REBALANCED EVERY HOUR BY PUBLIC RULES  ·  LIVE INDEX",
                    fS,
                    132,
                    CYAN + (int(255 * a2),),
                ),
            )
        )
        img = put(img, glow(lay, 8))
        img = put(img, lay)
        bl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bl)
        x0, x1, y0, rowh = 330, 1110, 178, 50
        mx = max(w for _, w in bars)
        for k, (tk, wv) in enumerate(bars):
            p = ease((t - 3.4 - k * 0.12) / 0.8) * a2
            if p <= 0:
                continue
            y = y0 + k * rowh
            L = int((x1 - x0) * (wv / mx) * p)
            f = k / 9
            col = tuple(int(PINK[j] + (CYAN[j] - PINK[j]) * f) for j in range(3))
            bd.rounded_rectangle(
                [x0, y + 8, x0 + max(L, 6), y + rowh - 10], radius=12, fill=col + (int(235 * a2),)
            )
            bb = bd.textbbox((0, 0), tk, font=fB)
            bd.text((x0 - 20 - (bb[2] - bb[0]), y + 9), tk, font=fB, fill=WHITE + (int(255 * a2),))
            if p > 0.6:
                bd.text(
                    (x0 + L + 14, y + 9),
                    f"{wv * min(1, p / 0.95):.1f}%",
                    font=fB,
                    fill=YEL + (int(255 * a2 * min(1, (p - 0.6) / 0.3)),),
                )
        img = put(img, glow(bl, 10, 0.8))
        img = put(img, bl)
    # S3 fees
    a3 = win(t, 8.0, 12.3, 0.35, 0.4)
    if a3 > 0:
        s = 0.9 + 0.1 * back((t - 8.0) / 0.7)
        tl = grad_text("100% OF FEES", fBig, YEL, ORANGE, W / 2, 175, s, a3)
        img = put(img, glow(tl, 18, 1.4))
        img = put(img, tl)
        a = a3 * ease((t - 8.45) / 0.4)
        if a > 0:
            tl2 = grad_text("GO TO HOLDERS", F(ANTON, 96), HOT, PINK, W / 2, 315, 1.0, a)
            img = put(img, glow(tl2, 16, 1.4))
            img = put(img, tl2)
        lines = [
            "PAID AUTOMATICALLY, EVERY DAY",
            "THE DEV NEVER SIGNS A PAYMENT",
            "HOLD LONGER, EARN UP TO 10×",
        ]
        for k, ln in enumerate(lines):
            a = a3 * ease((t - 9.1 - k * 0.45) / 0.4)
            if a <= 0:
                continue
            dx = 40 * (1 - ease((t - 9.1 - k * 0.45) / 0.4))
            lay = text_layer(
                lambda d, ln=ln, k=k, a=a, dx=dx: (
                    d.ellipse(
                        [340 + dx, 432 + k * 70, 358 + dx, 450 + k * 70],
                        fill=CYAN + (int(255 * a),),
                    ),
                    d.text((380 + dx, 420 + k * 70), ln, font=fL, fill=WHITE + (int(255 * a),)),
                )
            )
            img = put(img, glow(lay, 8))
            img = put(img, lay)
    # S4 end card
    a4 = win(t, 12.1, 15.2, 0.45, 0.01)
    if a4 > 0:
        s = back((t - 12.1) / 0.7)
        sz = int(250 * max(0.01, s))
        lg = logo.resize((sz, sz), Image.LANCZOS)
        m = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(m).ellipse([0, 0, sz, sz], fill=int(255 * a4))
        ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        cx, cy = 330, H // 2 - 10
        rd.ellipse(
            [cx - sz / 2 - 8, cy - sz / 2 - 8, cx + sz / 2 + 8, cy + sz / 2 + 8],
            outline=PINK + (int(255 * a4),),
            width=6,
        )
        img = put(img, glow(ring, 16, 1.5))
        img = put(img, ring)
        img.paste(lg, (cx - sz // 2, cy - sz // 2), m)
        tl = grad_text("GTASP10", F(ANTON, 120), HOT, YEL, 830, 250, 1.0, a4)
        img = put(img, glow(tl, 18, 1.4))
        img = put(img, tl)
        a = a4 * ease((t - 12.6) / 0.4)
        if a > 0:
            lay = text_layer(
                lambda d: (
                    center_text(d, "gtasp10.xyz", fURL, 395, CYAN + (int(255 * a),), 830),
                    center_text(d, "@GTASP10 on X", fB, 480, WHITE + (int(255 * a),), 830),
                )
            )
            img = put(img, glow(lay, 12, 1.2))
            img = put(img, lay)
        a = a4 * ease((t - 13.0) / 0.4)
        if a > 0:
            lay = text_layer(
                lambda d: center_text(
                    d,
                    "Not financial advice. Memecoins are high risk.",
                    fSmall,
                    H - 36,
                    (200, 190, 220, int(230 * a)),
                )
            )
            img = put(img, lay)
    return img.convert("RGB")


out = sys.argv[4]
p = subprocess.Popen(  # nosec B603 B607 - fixed ffmpeg argv
    [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        out,
    ],
    stdin=subprocess.PIPE,
)
only = sys.argv[5:] if len(sys.argv) > 5 else None
if only:
    for s in only:
        frame(int(float(s) * FPS)).save(f"/tmp/prev_{s}.jpg", quality=85)
    p.stdin.close()
    p.wait()
    sys.exit()
for i in range(N):
    p.stdin.write(frame(i).tobytes())
p.stdin.close()
p.wait()
print("done", out)
