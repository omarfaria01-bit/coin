# GTASP10 logo palettes — B (vice sunset) is LIVE and the default (kiwi 18 Nov: black logo disappears on X dark mode)

Recolored versions of `../logo_template.jpg`. Same concept (heist bag, 6 stars, coin stacks, GTASP10),
but bright backgrounds so the avatar reads on X dark (#000) and light (#fff).
The coin-face ellipses are untouched, so the hourly renderer still pastes the live top-10 logos.

| file | look |
|---|---|
| logo_template_neon_night.jpg | A: hot-pink → purple radial background, deep-purple bag, cyan rim light, gold neon stars |
| logo_template_vice_sunset.jpg | B: purple → pink → orange sunset background, deep-teal bag, pink rim light |
| logo_template_miami_teal.jpg | C: cyan/teal background, magenta-purple bag, pink rim light |

No renderer code change needed: pick one with the existing env var (drop-in), after kiwi APPROVES:

```
# /etc/systemd/system/gtasp10-logo.service.d/palette.conf
[Service]
Environment=GTASP10_LOGO_TEMPLATE=/usr/local/share/gtasp10/logo_template_vice_sunset.jpg
```

Rebuild: `segment_bag.py` (OpenCV GrabCut → bag_mask.png), then `recolor.py` (OpenCV + numpy, offline only;
the server renderer stays PIL-only).
