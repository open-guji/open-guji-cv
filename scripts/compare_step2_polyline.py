# -*- coding: utf-8 -*-
"""Step2 列图「直线边线 vs 三段折线边线」并排对照，用来目视折线有没有把
邻列界行/切进字的问题修掉。

    python scripts/compare_step2_polyline.py 151 119            # vol01
    python scripts/compare_step2_polyline.py --book vol02 95     # 输出 output/<book>/step2_compare_<pages>.png

"直线"用 `BorderDetectionResult.verticals_straight`（拟合前留下的直线），不是从
三段线的 x_at_top/slope 反推——那是第一段的外推，不是原直线。
每列并排：S=直线（红框）/ P=折线（绿框）。
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from open_guji_cv.utils.border_geometry import detect_borders  # noqa: E402
from open_guji_cv.utils.column_projection import warp_page_columns  # noqa: E402

RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))
SC = 0.42


def work(args):
    book, page, cols = args
    gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
    res = detect_borders(gray, expected_cols=9)
    res_s = dataclasses.replace(res, verticals=res.verticals_straight, vline_segments=1)
    poly = {w.col: img for w, img in warp_page_columns(gray, res)}
    stra = {w.col: img for w, img in warp_page_columns(gray, res_s)}
    tiles = []
    for c in cols:
        for tag, img, col in (("S", stra[c], (0, 40, 235)), ("P", poly[c], (0, 150, 0))):
            t = cv2.cvtColor(cv2.resize(img, None, fx=SC, fy=SC, interpolation=cv2.INTER_AREA),
                             cv2.COLOR_GRAY2BGR)
            t = cv2.copyMakeBorder(t, 0, 0, 2, 2, cv2.BORDER_CONSTANT, value=col)
            hdr = np.full((22, t.shape[1], 3), 248, np.uint8)
            cv2.putText(hdr, f"c{c}{tag}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)
            tiles.append(np.vstack([hdr, t]))
        tiles.append(np.full((tiles[-1].shape[0], 10, 3), 255, np.uint8))
    H = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, 0, cv2.BORDER_CONSTANT,
                                value=(255, 255, 255)) for t in tiles]
    strip = np.hstack(tiles)
    hdr = np.full((26, strip.shape[1], 3), 235, np.uint8)
    w80 = "--" if res.bend_w80_med is None else f"{res.bend_w80_med:.1f}"
    cv2.putText(hdr, f"{book}/{page}  seg={res.vline_segments}  w80 {w80}  S=straight  P=polyline",
                (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)
    return np.vstack([hdr, strip])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--cols", default="2,4,6,8")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    cols = [int(x) for x in a.cols.split(",")]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        imgs = list(ex.map(work, [(a.book, p, cols) for p in a.pages]))
    H = max(i.shape[0] for i in imgs)
    imgs = [cv2.copyMakeBorder(i, 0, H - i.shape[0], 0, 24, cv2.BORDER_CONSTANT,
                               value=(255, 255, 255)) for i in imgs]
    out = ROOT / "output" / a.book / f"step2_compare_{'_'.join(a.pages)}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.hstack(imgs))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
