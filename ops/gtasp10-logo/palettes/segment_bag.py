# ruff: noqa
# Offline tool (OpenCV + numpy); not used by the server renderer.
import cv2
import numpy as np

im = cv2.imread("logo_template.jpg")
H, W = im.shape[:2]
old = cv2.imread("fg_mask_grabcut_rect.png", 0)
m = np.full((H, W), cv2.GC_BGD, np.uint8)
m[175:705, 105:920] = cv2.GC_PR_BGD
# probable fg: rounded bag body
cv2.ellipse(m, (512, 520), (390, 175), 0, 0, 360, cv2.GC_PR_FGD, -1)
m[old > 0] = cv2.GC_PR_FGD
# definite fg core
cv2.ellipse(m, (500, 530), (300, 120), 0, 0, 360, cv2.GC_FGD, -1)
m[cv2.erode(old, np.ones((15, 15), np.uint8)) > 0] = cv2.GC_FGD
bgd = np.zeros((1, 65))
fgd = np.zeros((1, 65))
cv2.grabCut(im, m, None, bgd, fgd, 10, cv2.GC_INIT_WITH_MASK)
fg = np.where((m == 1) | (m == 3), 255, 0).astype(np.uint8)
n, lab, st, _ = cv2.connectedComponentsWithStats(fg)
k = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
fg = np.where(lab == k, 255, 0).astype(np.uint8)
cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
fill = np.zeros_like(fg)
cv2.drawContours(fill, cnts, -1, 255, -1)
fill = cv2.morphologyEx(fill, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
cv2.imwrite("bag_mask.png", fill)
ov = im.copy()
ov[fill == 0] = (0, 0, 180)
cv2.imwrite("bag_mask_check.jpg", ov)
