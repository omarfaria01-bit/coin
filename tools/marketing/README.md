# Promo video (handoff from the manager session, 18 Nov 21:30 Rome)

`promo_video.py` renders a 15 s, 1280×720 motion-graphics promo from the live index (PIL frames → ffmpeg, no AI, no paid service).
Scenes: title · top-10 bars with real weights · "100% of fees go to holders" · end card with logo, gtasp10.xyz, @GTASP10, NFA.

```
git show origin/index-data:index/out/<latest>.json > idx.json
python3 tools/marketing/promo_video.py idx.json web/wallpaper.jpg web/logo-400.png out.mp4          # full render (~40 s)
python3 tools/marketing/promo_video.py idx.json web/wallpaper.jpg web/logo-400.png /tmp/x.mp4 1.6 5.6 10.6 13.8   # preview stills
```
Needs: python3 + Pillow, ffmpeg, fonts Anton / Archivo Black / Poppins (google-fonts). kiwi liked this one; the GPU clips (ComfyUI LTX/Wan in `C:\AI`) were rejected.

Other video tools each Claude account can enable for itself (claude.ai → plugins/skills): Remotion (`remotion:*` skills, React-based video),
`anthropic-skills:video-making`, Higgsfield connector (paid credits; the manager's account had only 10 free).
Rules: no copyrighted characters/logos (no Rockstar/GTA marks), every claim true (payouts "start the day after launch" until live), kiwi approves posts.
