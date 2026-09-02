# -*- coding: utf-8 -*-
"""把三段折线的拟合结果导成金标 JSON（人裁认可的线/段才标 approved）。

    python scripts/export_vline_polyline_gold.py 11 119 151

线号**从右到左、从 1 开始**，跟 `BorderDetectionResult.verticals` 的顺序一致
（`verticals[0]` 最右）。每条线记：
  `polyline`  {x_at_top, slope, k2, k3, y1, y2}  —— 三段折线参数
  `straight`  {x_at_top, slope}                  —— 拟合前的直线，量"改前"用
  `segments`  逐段 {w80, peak}                   —— 该段贴真墨的程度
  `approved`  逐段 true/false                    —— 人裁：这一段对不对
写 `open-guji-dataset/border-detection/vline-polyline/<book>_<page>.json`。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from open_guji_cv.utils.border_geometry import detect_borders, gutter_projection  # noqa: E402

RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))
OUT = ROOT.parent / "open-guji-dataset" / "border-detection" / "vline-polyline"

# 人裁结果（用户 2026-09-02 看逐列叠图给的）：线号从右数，列出**不对**的段。
# 没列进来的线/段 = 用户明确说"其他所有线都很完美"。
REJECTED: dict[tuple[str, str], dict[int, list[int]]] = {
    ("vol01", "11"): {1: [1, 2, 3]},          # 整条线位置就错（列距 155 vs 183），见 README
    ("vol01", "119"): {1: [2, 3], 3: [3], 4: [1]},
    ("vol01", "151"): {},
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--book", default="vol01")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for page in a.pages:
        gray = cv2.imread(str(RAW / a.book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            print(f"{a.book}/{page}: 原图缺失"); continue
        h, w = gray.shape
        binm = (gray < 128).astype(np.uint8)
        res = detect_borders(gray, expected_cols=9)
        rej = REJECTED.get((a.book, page), {})
        lines = []
        for no, (s, p) in enumerate(zip(res.verticals_straight, res.verticals), 1):
            xc = p.x_at(h / 2.0)
            yt, yb = float(res.top.y_at(xc)), float(res.bottom.y_at(xc))
            ky = [yt] + p.knots() + [yb]
            segs = []
            for i, (aa, bb) in enumerate(zip(ky, ky[1:]), 1):
                g = gutter_projection(binm, p.x_at, int(aa) + 10, int(bb) - 10, w)
                segs.append(dict(seg=i,
                                 w80=None if g is None else int(g[2]),
                                 peak=None if g is None else round(float(g[0]), 3),
                                 approved=i not in rej.get(no, [])))
            lines.append(dict(
                no=no,
                polyline=dict(x_at_top=round(p.x_at_top, 4), slope=round(p.slope, 6),
                              k2=None if p.k2 is None else round(p.k2, 6),
                              k3=None if p.k3 is None else round(p.k3, 6),
                              y1=None if p.y1 is None else round(p.y1, 2),
                              y2=None if p.y2 is None else round(p.y2, 2)),
                straight=dict(x_at_top=round(s.x_at_top, 4), slope=round(s.slope, 6)),
                segments=segs))
        doc = dict(book=a.book, page=page, width=w, height=h,
                   coord_space="new: origin top-right, x leftward, y down; 线号从右到左从1开始",
                   vline_segments=res.vline_segments,
                   bend_w80_med=res.bend_w80_med, bend_w80_max=res.bend_w80_max,
                   label_origin="human", labeled_at="2026-09-02",
                   note="用户看逐列叠图逐段裁决；approved=false 的段见 README",
                   lines=lines)
        path = OUT / f"{a.book}_{page}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        ok = sum(1 for L in lines for sg in L["segments"] if sg["approved"])
        tot = sum(len(L["segments"]) for L in lines)
        print(f"{path}  approved {ok}/{tot} 段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
