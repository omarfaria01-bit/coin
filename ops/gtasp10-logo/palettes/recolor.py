# ruff: noqa
# Offline tool (OpenCV + numpy); not used by the server renderer.
import cv2
import numpy as np

src = cv2.imread("logo_template.jpg").astype(np.float32) / 255.0
H, W = src.shape[:2]
fg = cv2.imread("bag_mask.png", 0).astype(np.float32) / 255.0
hsv = cv2.cvtColor((src * 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
sat = hsv[..., 1] / 255.0
lum = 0.114 * src[..., 0] + 0.587 * src[..., 1] + 0.299 * src[..., 2]
band = np.zeros_like(fg)
band[int(H * 0.2) : int(H * 0.68), int(W * 0.08) : int(W * 0.92)] = 1
extra = cv2.morphologyEx(
    ((lum > 0.07) * band).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)
).astype(np.float32)
extra = cv2.morphologyEx(extra, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
fg_s = cv2.GaussianBlur(fg, (0, 0), 1.5)
# decor (stars + GTASP10 text) outside the bag
decor = np.clip((lum - 0.17) / 0.18, 0, 1) * (1 - fg) * (1 - band)
decor = cv2.GaussianBlur(decor, (0, 0), 0.7)
# coins/red stripes keep original (saturated); bag (grey) gets gradient-mapped
keep = np.clip((sat - 0.22) / 0.2, 0, 1) * np.clip((lum - 0.08) / 0.1, 0, 1)
# keep the grey face ellipses too (renderer pastes logos there): grey & bright, upper area
faces = ((lum > 0.25) & (sat < 0.15)).astype(np.float32)
faces[int(H * 0.42) :, :] = 0
keep = np.maximum(keep, cv2.GaussianBlur(faces, (0, 0), 1)) * fg


def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)], np.float32) / 255  # BGR


def gmap(l, stops):
    xs = np.array([s[0] for s in stops])
    cs = np.stack([hexc(s[1]) for s in stops])
    out = np.zeros(l.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(l, xs, cs[:, c])
    return out


yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)


def radial(c0, c1, c2, cx=0.5, cy=0.45):
    r = np.sqrt((xx / W - cx) ** 2 + (yy / H - cy) ** 2) / 0.72
    return gmap(np.clip(r, 0, 1), [(0, c0), (0.55, c1), (1, c2)])


def vertical(stops):
    return gmap(yy / H, stops)


def glow(mask, color, sigma, strength):
    g = cv2.GaussianBlur(mask, (0, 0), sigma)
    return g[..., None] * hexc(color) * strength


def build(name, bg, bag_stops, rim, rim2, star_col, text_col, text_edge):
    # background with faint original texture
    tex = cv2.GaussianBlur(lum, (0, 0), 1.2)
    tex = (tex - tex.mean()) * 0.9
    img = np.clip(bg + tex[..., None], 0, 1)
    # vignette edges a bit for depth
    # bag: gradient map, gentle contrast curve
    l = np.clip(lum * 1.6, 0, 1) ** 0.85
    bag = gmap(l, bag_stops)
    bag = bag * (1 - keep[..., None]) + src * keep[..., None]
    # rim light: edge of fg
    edge = np.clip(fg - cv2.erode(fg, np.ones((9, 9), np.uint8)), 0, 1)
    img = img + glow(fg, rim, 28, 0.55) * (1 - fg_s[..., None])  # outer halo
    img = img * (1 - fg_s[..., None]) + bag * fg_s[..., None]
    img = img + glow(edge, rim2, 3, 0.9) * fg_s[..., None]  # inner rim
    # decor: stars upper part, text lower part
    top = (yy < H * 0.2).astype(np.float32)
    star = decor * top
    text = decor * (1 - top)
    img = img + glow(star, star_col, 10, 1.2)
    img = img * (1 - star[..., None]) + hexc(star_col)[None, None, :] * star[..., None]
    # text: dark edge/shadow then fill (keep grunge via lum)
    sh = cv2.GaussianBlur(cv2.dilate(text, np.ones((7, 7), np.uint8)), (0, 0), 3)
    img = img * (1 - 0.85 * sh[..., None]) + hexc(text_edge) * 0.85 * sh[..., None]
    img = img + glow(text, text_edge, 14, 0.6)
    tfill = gmap(np.clip(lum * 1.3, 0, 1), [(0, text_col[0]), (1, text_col[1])])
    img = img * (1 - text[..., None]) + tfill * text[..., None]
    img = np.clip(img, 0, 1)
    out = (img * 255).astype(np.uint8)
    cv2.imwrite(f"logo_template_{name}.jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 94])


V = {
    "neon_night": dict(
        bg=radial("#ff4fd8", "#8b2fd6", "#2a0a5e"),
        bag_stops=[(0, "#12002a"), (0.35, "#3b0a78"), (0.7, "#7c3aed"), (1, "#c4f5ff")],
        rim="#22e3ff",
        rim2="#7df9ff",
        star_col="#ffe066",
        text_col=("#ffffff", "#ffffff"),
        text_edge="#3b0764",
    ),
    "vice_sunset": dict(
        bg=vertical([(0, "#2b0b5a"), (0.38, "#c2187a"), (0.7, "#ff5e5b"), (1, "#ffb347")]),
        bag_stops=[(0, "#011f2a"), (0.35, "#064e63"), (0.7, "#0ea5b7"), (1, "#d6fbff")],
        rim="#ff2d95",
        rim2="#ffd1f0",
        star_col="#fff3b0",
        text_col=("#fff6fb", "#ffffff"),
        text_edge="#2b0b5a",
    ),
    "miami_teal": dict(
        bg=radial("#5ff3ff", "#11a7c9", "#0b3a6e", cy=0.42),
        bag_stops=[(0, "#1a0326"), (0.35, "#4c0d5e"), (0.7, "#b0247f"), (1, "#ffd6ef")],
        rim="#ff2d95",
        rim2="#ff9be0",
        star_col="#ffe066",
        text_col=("#ffffff", "#ffffff"),
        text_edge="#4c0d5e",
    ),
}
for k, v in V.items():
    build(k, **v)
    print(k)
