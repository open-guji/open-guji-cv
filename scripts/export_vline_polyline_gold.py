# -*- coding: utf-8 -*-
"""把三段折线的拟合结果导成金标 JSON（人裁认可的线/段才标 approved）。

    python scripts/export_vline_polyline_gold.py 11 119 151

线号**从右到左、从 1 开始**，跟 `BorderDetectionResult.verticals` 的顺序一致
（`verticals[0]` 最右）。每条线记：
  `gold`        金标位置（人工拖过就是人工的，否则=算法的），下游要用这个
  `gold_origin` "human" | "algorithm"
  `polyline`    算法拟合出来的三段折线，留作对照
  `straight`    拟合前的直线，量"改前"用
  `manual`      人工拖的四端点位移/坐标（只有 gold_origin=human 才有）
  `segments`    逐段 {w80, peak, approved}
  `limitation`  三段模型表达不了这条线时的说明
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
from open_guji_cv.utils.border_geometry import (  # noqa: E402
    _from_knots, detect_borders, gutter_projection)


def _dump(v):
    return dict(x_at_top=round(v.x_at_top, 4), slope=round(v.slope, 6),
                k2=None if v.k2 is None else round(v.k2, 6),
                k3=None if v.k3 is None else round(v.k3, 6),
                y1=None if v.y1 is None else round(v.y1, 2),
                y2=None if v.y2 is None else round(v.y2, 2))

RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))
OUT = ROOT.parent / "open-guji-dataset" / "border-detection" / "vline-polyline"

# 人裁结果（用户 2026-09-02 看逐列叠图给的）。线号从右数。
#
# REJECTED[(book,page)][线号] = [不对的段号...]
# 没列进来的线/段 = 用户明确说"其他所有线都很完美"。
REJECTED: dict[tuple[str, str], dict[int, list[int]]] = {
    ("vol01", "11"): {1: [1, 2, 3]},
    ("vol01", "119"): {1: [2, 3], 3: [3], 4: [1]},
    ("vol01", "151"): {},
}

# 人工拖出来的正确位置：四个折点相对**算法折线**的 x 位移（新坐标，向左为正）。
# 有这一项的线，金标位置以 `manual_polyline` 为准，`polyline` 只留作对照。
MANUAL_SHIFT: dict[tuple[str, str], dict[int, list[float]]] = {
    # vol01/11 L1：算法整条找错了位置（离 L2 只有 155px，该页列距中位 183px）。
    # 用户实拖：四端点 −20 / 0 / +20 / +20。**这条线本身很虚**，
    # `gutter_projection` 对算法线和金标线都返回"有效行不足"——位置只能靠人定，
    # 指标量不出来，所以 `segments[].w80/peak` 会是 null，别当成"金标不可信"。
    ("vol01", "11"): {1: [-20.0, 0.0, 20.0, 20.0]},
}

# 模型局限（不是标注失败，是三段模型表达不了的形状）。
LIMITATION: dict[tuple[str, str], dict[int, str]] = {
    ("vol01", "119"): {
        1: "真线是「第一段直、第二段弯、第三段直」——三段模型每段都是直线，"
           "表达不了中间那段的弯。用户裁定：不增加段数就调不动，按现状收为金标。",
    },
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
        man = MANUAL_SHIFT.get((a.book, page), {})
        lim = LIMITATION.get((a.book, page), {})
        lines = []
        for no, (s, p) in enumerate(zip(res.verticals_straight, res.verticals), 1):
            xc = p.x_at(h / 2.0)
            yt, yb = float(res.top.y_at(xc)), float(res.bottom.y_at(xc))
            ky = [yt] + p.knots() + [yb]
            gold_line, manual = p, None
            if no in man:
                kx = [p.x_at(ky[j]) + man[no][j] for j in range(4)]
                gold_line = _from_knots(kx, ky)
                manual = dict(shift_px=man[no],
                              knots_x=[round(x, 2) for x in kx],
                              knots_y=[round(y, 2) for y in ky])
            segs = []
            for i, (aa, bb) in enumerate(zip(ky, ky[1:]), 1):
                g = gutter_projection(binm, gold_line.x_at, int(aa) + 10, int(bb) - 10, w)
                segs.append(dict(seg=i,
                                 w80=None if g is None else int(g[2]),
                                 peak=None if g is None else round(float(g[0]), 3),
                                 approved=i not in rej.get(no, [])))
            rec = dict(
                no=no,
                # 金标位置：有人工拖过就是人工的，否则是算法的
                gold=_dump(gold_line),
                gold_origin="human" if no in man else "algorithm",
                polyline=_dump(p),
                straight=dict(x_at_top=round(s.x_at_top, 4), slope=round(s.slope, 6)),
                segments=segs)
            if manual:
                rec["manual"] = manual
            if no in lim:
                rec["limitation"] = lim[no]
            lines.append(rec)
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
