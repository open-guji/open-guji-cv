"""GUJI-75 首查：vol02 p3 第 1 列（题列「欽定四庫全書總目卷」）——Step3 的格 vs 页面墨迹投影的字。只读。

用法：python3 col1_projection.py <vol02 p3 原图 3.png> <row_segment/p0003.json>
说明：row_segment 的 quad_page 横坐标是「第 1 列在右」的页坐标，对原图要用 W−x。"""
import json
import sys

import cv2
import numpy as np
import scipy.ndimage as nd

img, rsf = sys.argv[1], sys.argv[2]
im = cv2.imread(img, 0)
W = im.shape[1]
cc = [c for c in json.load(open(rsf))["cells"]["columns"] if c["col"] == 1][0] if "cells" in json.load(open(rsf)) else None
cells = cc["cells"]
cy = [round((c["quad_page"][0][1] + c["quad_page"][2][1]) / 2) for c in cells]
xs = [p[0] for c in cells[:13] for p in c["quad_page"]]
xc = W - int(np.mean(xs))
band = (im[:, xc - 70:xc + 70] < 128).sum(1).astype(float)
sm = nd.uniform_filter1d(band, 25)
th = 0.35 * sm[300:1700].max()
runs, inrun = [], False
for y in range(300, 1900):
    if sm[y] > th and not inrun:
        s, inrun = y, True
    if sm[y] <= th and inrun:
        runs.append((s, y))
        inrun = False
runs = [r for r in runs if r[1] - r[0] >= 40]      # 丢掉几像素的碎块
glyph = [(a + b) // 2 for a, b in runs]
print("Step3 格中心 y（前 13 个非空白格）：", cy[:13])
print("格间距：", [cy[i + 1] - cy[i] for i in range(12)])
print("墨迹投影字心 y（阈值 0.35×峰）：", glyph)
nine = glyph[:9]
print("前 9 个字心（对应『欽定四庫全書總目卷』9 字）：", nine, "字距均值 %.1f" % ((nine[-1] - nine[0]) / 8))
print("每个字最近的格：", [int(np.argmin([abs(g - y) for y in cy[:13]])) + 1 for g in nine])
