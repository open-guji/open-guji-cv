# -*- coding: utf-8 -*-
"""overview#427 第二批（研究，未进管线）：卷末大印「乾隆御覽之寶」的方框探测原型——负结果，见 HANDOFF_C1.md。

思路：横向闭运算补断线 → 长横段（1.5~6 列宽）两两配对成方框 → 两侧竖边覆盖 ≥70%。
vol04 全书 222 页命中 4 页（p3/p127/p130/p220），但 p3、p130 的框落在正文里（字的横笔被闭运算连成段），不能用。
用法：python seal_box_probe.py <scratch> <products/volNN> volNN [页…]"""
import sys, json, os, subprocess, statistics, cv2, numpy as np
B = "96mid1ogzk-欽定四庫全書總目武英殿刻本"
def page_img(S, vol, pg):
    p = os.path.join(S, 'img', f'{vol}_{pg}.png')
    if not os.path.exists(p):
        data = subprocess.run(['git', '-C', '/home/user/guji-workspace', 'show', f'HEAD:{B}/data_full/zongmu/{vol}/{pg}.png'], capture_output=True).stdout
        if not data: return None
        open(p, 'wb').write(data)
    return cv2.imread(p, cv2.IMREAD_GRAYSCALE)
def seal_boxes(gray, cw, dbg=False):
    b = (gray < 128).astype(np.uint8)
    L = max(3, int(1.5 * cw))
    bc = cv2.morphologyEx(b, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(cw / 6)), 5)))
    h = cv2.morphologyEx(bc, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(h, connectivity=8)
    segs = [tuple(st[i, :4]) for i in range(1, n) if 1.5 * cw <= st[i, 2] <= 6 * cw]
    if dbg: print('segs', segs)
    bv = cv2.morphologyEx(b, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, max(3, int(cw / 6)))))
    out = []
    for i, (x0, y0, w0, h0) in enumerate(segs):
        for (x1, y1, w1, h1) in segs[i + 1:]:
            if y1 < y0: (x0, y0, w0, h0), (x1, y1, w1, h1) = (x1, y1, w1, h1), (x0, y0, w0, h0)
            ov = min(x0 + w0, x1 + w1) - max(x0, x1)
            if ov < 0.8 * min(w0, w1): continue
            dy = y1 - y0; w = min(w0, w1)
            if not (0.6 * w <= dy <= 1.6 * w): continue
            X0, X1 = max(x0, x1), min(x0 + w0, x1 + w1)
            # 两条竖边：盒子左右端 cw/4 宽的带里，有一条纵向墨线覆盖 ≥ 70% 的高度
            def side(xa, xb):
                band = bv[y0:y1 + h1, max(0, xa):xb]
                return band.max(axis=1).mean() if band.size else 0
            sl = side(X0 - int(cw / 8), X0 + int(cw / 4)); sr = side(X1 - int(cw / 4), X1 + int(cw / 8))
            if dbg: print('pair', (X0, y0, X1, y1 + h1), round(sl, 2), round(sr, 2))
            if sl >= 0.7 and sr >= 0.7:
                out.append((int(X0), int(y0), int(X1), int(y1 + h1)))
    return out
if __name__ == '__main__':
    S, root, vol = sys.argv[1], sys.argv[2], sys.argv[3]
    pages = [int(x) for x in sys.argv[4:]] or sorted(int(f[1:5]) for f in os.listdir(os.path.join(root, 'row_segment')) if f.startswith('p'))
    for pg in pages:
        f = os.path.join(root, 'row_segment', f'p{pg:04d}.json')
        if not os.path.exists(f): continue
        cells = next(v for k, v in json.load(open(f)).items() if k == 'cells')
        ws = [np.ptp(np.asarray(x['quad_page'])[:, 0]) for c in cells['columns'] for x in c['cells'] if x.get('quad_page')]
        if not ws: continue
        g = page_img(S, vol, pg)
        if g is None: continue
        bx = seal_boxes(g, statistics.median(ws), dbg=len(sys.argv) > 4)
        if bx or len(sys.argv) > 4: print(pg, round(statistics.median(ws)), bx, flush=True)
