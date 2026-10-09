# -*- coding: utf-8 -*-
"""卷末页「乾隆御覽之寶」印章盖空栏的判空可行性（overview#493，只量不改 steps/）。
原图是纯 1-bit 黑白（无红色通道），颜色判法不可用；这条用**固定印章模板匹配**：每个卷末页盖的是同一方印，
位置几乎不变（约 x=830,y=330、660×680 px）。
用法：python seal_page_detect.py <data_full/zongmu 目录> <册 [册…]>
模板取自 vol05 p188（crop x820–1480,y330–1010），1/4 缩放，TM_CCOEFF_NORMED，只看模板预期位置 ±100px 的窗口。
输出每册窗口内得分最高的页；真印章页 ≥0.39、其余页 ≤0.28（四册合计 ~720 页）。"""
import sys, os
import cv2

raw, books = sys.argv[1], sys.argv[2:]
tpl_src = cv2.imread(os.path.join(raw, "vol05", "188.png"), 0)
T = tpl_src[330:1010, 820:1480]
f = 0.25
Ts = cv2.resize(T, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
for v in books:
    sc = []
    for p in range(1, 400):
        fn = os.path.join(raw, v, f"{p}.png")
        if not os.path.exists(fn):
            break
        a = cv2.resize(cv2.imread(fn, 0), None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        if a.shape[0] < Ts.shape[0] or a.shape[1] < Ts.shape[1]:
            continue
        m = cv2.matchTemplate(a, Ts, cv2.TM_CCOEFF_NORMED)
        w = m[max(0, int(230 * f)):int(430 * f) + 1, max(0, int(730 * f)):int(930 * f) + 1]
        if w.size:
            sc.append((p, round(float(w.max()), 3)))
    s = sorted(sc, key=lambda t: -t[1])
    print(v, "窗口内最高：", s[:6], "｜第7–10名：", s[6:10])
