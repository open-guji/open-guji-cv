# -*- coding: utf-8 -*-
"""整页叠图看每一列的折线效果：红=拟合前直线，绿=三段折线，黄点=折点，
每条线顶上标 w80 直线→折线（装下 80% 墨的最窄 x 跨度，越小越贴）。
线号**从右到左、从 1 开始**，跟 `verticals` 的顺序一致。

    python scripts/draw_polyline_overlay.py 151 119 11             # vol01
    python scripts/draw_polyline_overlay.py --book vol02 95 --scale 0.6
输出 output/<book>/polyline_overlay_<page>.png
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from open_guji_cv.utils.border_geometry import detect_borders, gutter_projection  # noqa: E402

RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))


def work(args):
    book, page, scale = args
    gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
    h, w = gray.shape
    binm = (gray < 128).astype(np.uint8)
    res = detect_borders(gray, expected_cols=9)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    # **从右到左编号**（项目约定：verticals 已按 x_at_top 升序 = 最右在前）。
    # 头一版按 x_old 升序标号，标出来是从左到右、跟约定正好反着，对不上话。
    pairs = list(zip(res.verticals_straight, res.verticals))
    labels = []
    for i, (s, p) in enumerate(pairs, 1):
        xc = p.x_at(h / 2.0)
        y0, y1 = int(res.top.y_at(xc)), int(res.bottom.y_at(xc))
        a = gutter_projection(binm, s.x_at, y0 + 30, y1 - 30, w)
        b = gutter_projection(binm, p.x_at, y0 + 30, y1 - 30, w)
        # 红：直线；绿：折线（新坐标 x 向左 => 旧坐标 (w-1)-x）
        for y in range(max(0, y0 - 40), min(h, y1 + 40), 2):
            xs_ = int(round((w - 1) - s.x_at(y)))
            if 0 <= xs_ < w:
                img[y, max(0, xs_ - 1):xs_ + 2] = (0, 40, 235)
        for y in range(max(0, y0 - 40), min(h, y1 + 40)):
            xp = int(round((w - 1) - p.x_at(y)))
            if 0 <= xp < w:
                img[y, max(0, xp - 2):xp + 3] = (0, 170, 0)
        for ky in p.knots():
            cv2.circle(img, (int(round((w - 1) - p.x_at(ky))), int(ky)), 11, (0, 215, 255), -1)
            cv2.circle(img, (int(round((w - 1) - p.x_at(ky))), int(ky)), 11, (0, 0, 0), 2)
        wa = "--" if a is None else str(a[2])
        wb = "--" if b is None else str(b[2])
        labels.append((int(round((w - 1) - p.x_at(y0))), f"c{i} {wa}>{wb}"))
    out = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    band = np.full((60, out.shape[1], 3), 245, np.uint8)
    for x, txt in labels:
        cv2.putText(band, txt, (max(0, int(x * scale) - 34), 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (20, 20, 20), 1)
    seg = res.vline_segments
    w80 = "--" if res.bend_w80_med is None else f"{res.bend_w80_med:.1f}"
    cv2.putText(band, f"{book}/{page}   seg={seg}   w80 med {w80}   red=straight  green=polyline  yellow=knots",
                (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1)
    return page, np.vstack([band, out])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    outdir = ROOT / "output" / a.book
    outdir.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for page, img in ex.map(work, [(a.book, p, a.scale) for p in a.pages]):
            out = outdir / f"polyline_overlay_{page}.png"
            cv2.imwrite(str(out), img)
            print(out, img.shape)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
