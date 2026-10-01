"""X2 道：在重跑 cell_shrink 时，挂钩抓每格**裁紧前**图块的原始缺陷量（不改 extractor 源码，
不动 cell_shrink 指纹）。

用法（单进程串行，钩子才在同一进程里）：
  GUJI_WORKSPACE=… GUJI_PRODUCTS_DIR=<产物沙箱> python capture_features.py <book> <pages> <out.pkl>
产物沙箱里 Step1–3 必须已有；本脚本 --force 重跑 cell_shrink 并抓取。

抓的量（键 = (book, page, col, idx)，idx 是 0 起格号 = CharRec.idx）：
  现行各标记的**原始量**：rule_bar/edge_blob/frame_bars/x_gap/off_center/top_band/bot_band、
  bar_crosses（_bar_crosses_column 返回）、aspect（bad_seg 的量）；
  新增：连通体统计、四边缘带墨比例、宽高比、ink、cell_h/col_w。
"""
from __future__ import annotations

import pickle
import sys

import cv2
import numpy as np

from open_guji_cv.clustering import extractor as ex

SINK: dict = {}
_orig_flags = ex._defect_flags
_orig_bar = ex._bar_crosses_column


def _frame_ctx():
    f = sys._getframe(2)
    loc = f.f_locals
    return f, loc


def _extra(gray: np.ndarray) -> dict:
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    b = (gray < ex.BINARY_THRESHOLD_PATCH).astype(np.uint8)
    tot = int(b.sum())
    d = {"p_h": h, "p_w": w, "p_ink": tot / max(1, h * w)}
    if tot == 0:
        d.update(n_cc=0, cc1=0.0, cc2=0.0, cc1_h=0.0, cc1_w=0.0, cc1_cx=0.0, cc1_cy=0.0,
                 ink_l=0.0, ink_r=0.0, ink_t=0.0, ink_b=0.0, row_occ=0.0, col_occ=0.0,
                 span_h=0.0, span_w=0.0, cx=0.0, cy=0.0)
        return d
    n, _, st, cen = cv2.connectedComponentsWithStats(b, 8)
    areas = sorted((int(a) for a in st[1:, 4]), reverse=True)
    k = int(np.argmax(st[1:, 4])) + 1
    d["n_cc"] = int(sum(1 for a in areas if a >= 0.02 * tot))
    d["cc1"] = areas[0] / tot
    d["cc2"] = (areas[1] / tot) if len(areas) > 1 else 0.0
    d["cc1_h"] = st[k][3] / h
    d["cc1_w"] = st[k][2] / w
    d["cc1_cx"] = float(cen[k][0] / w)
    d["cc1_cy"] = float(cen[k][1] / h)
    e = max(2, int(0.08 * min(h, w)))
    d["ink_l"] = int(b[:, :e].sum()) / tot
    d["ink_r"] = int(b[:, -e:].sum()) / tot
    d["ink_t"] = int(b[:e].sum()) / tot
    d["ink_b"] = int(b[-e:].sum()) / tot
    rows = np.nonzero(b.any(axis=1))[0]
    cols = np.nonzero(b.any(axis=0))[0]
    d["span_h"] = (rows.max() - rows.min() + 1) / h
    d["span_w"] = (cols.max() - cols.min() + 1) / w
    d["row_occ"] = len(rows) / h
    d["col_occ"] = len(cols) / w
    d["cx"] = float((cols.mean() - w / 2) / w)
    d["cy"] = float((rows.mean() - h / 2) / h)
    return d


def _flags_hook(gray):
    f = sys._getframe(1)
    loc = f.f_locals
    r = _orig_flags(gray)
    try:
        idx = int(loc["idx"])
        col = loc.get("col")
        key = (str(loc.get("book_id") or loc.get("book")), str(loc.get("page")), int(col["index"]), idx)
    except Exception:
        return r
    feat = ex._defect_features(gray)
    feat["off_center"] = ex._off_center_frac(gray)
    feat["top_band"], feat["bot_band"] = ex._boundary_band_fracs(gray)
    feat["flags_part"] = list(r)
    feat["cell_h"] = float(loc.get("cell_h", 0.0))
    feat["col_w"] = float(loc.get("col_w", 0.0))
    feat["aspect"] = feat["cell_h"] / max(feat["col_w"], 1e-6)
    feat.update(_extra(gray))
    SINK[key] = feat
    return r


def _bar_hook(page, patch, x0, x1, y0):
    r = _orig_bar(page, patch, x0, x1, y0)
    f = sys._getframe(1)
    loc = f.f_locals
    try:
        col = loc.get("col")
        key = (str(loc.get("book_id") or loc.get("book")), str(loc.get("page")), int(col["index"]), int(loc["idx"]))
        if key in SINK:
            SINK[key]["bar_crosses"] = bool(r)
    except Exception:
        pass
    return r


def main():
    book, pages, out = sys.argv[1], sys.argv[2], sys.argv[3]
    ex._defect_flags = _flags_hook
    ex._bar_crosses_column = _bar_hook
    from open_guji_cv.__main__ import main as cli
    import os
    ws = os.environ["GUJI_WORKSPACE"]
    sys.argv = ["guji-cv", "step", "cell_shrink", book, "--pages", pages, "--force", "--jobs", "1", "-w", ws]
    try:
        cli()
    except SystemExit:
        pass
    pickle.dump(SINK, open(out, "wb"))
    print("captured", len(SINK))


if __name__ == "__main__":
    main()
