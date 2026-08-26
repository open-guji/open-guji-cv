"""比两份 phase3 网格目录：骑线比 + 每列格线位移 + 复切列清单。

改切分层的 A/B 必须整册跑（run_book 有跨页统计，只跑几页 cell_h/相位
就全变了，2026-08-26 踩过）。这里只做「跑完之后怎么读」：
  骑线比 = 内部格线上的墨 / 格心墨（越低越好，全书中位 0.38）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.grid_segment import (_smooth, column_projection,
                                                  deshear)


def col_straddle(img, col, cell_h):
    cells = [c for c in col.get("cells", []) if c.get("type") != "margin"]
    if len(cells) < 3:
        return None
    x0, x1 = max(0, int(col["left_x"]) + 2), min(img.shape[1],
                                                 int(col["right_x"]) - 2)
    if x1 - x0 < 8:
        return None
    sm = _smooth(column_projection(img[:, x0:x1]), cell_h)
    L = len(sm)
    g = lambda y: float(sm[min(max(int(round(y)), 0), L - 1)])
    lines = [c["y_top"] for c in cells] + [cells[-1]["y_bottom"]]
    ctr = [(c["y_top"] + c["y_bottom"]) / 2 for c in cells]
    cv_ = float(np.mean([g(y) for y in ctr]))
    if cv_ <= 1:
        return None
    return float(np.mean([g(y) for y in lines[1:-1]])) / cv_


def load(d: Path, page: str):
    p = d / f"{page}_char_grid.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    old_d, new_d = Path(a.old), Path(a.new)
    pages = sorted((f.stem.replace("_char_grid", "")
                    for f in new_d.glob("*_char_grid.json")), key=lambda s: int(s))
    rows, recut, moved = [], [], 0
    for pg in pages:
        o, n = load(old_d, pg), load(new_d, pg)
        if not o or not n:
            continue
        img = cv2.imread(f"output/{a.book}/{pg}.png", 0)
        if img is None:
            continue
        img_o = deshear(img, o["grid"].get("shear", 0.0) or 0.0)
        img_n = deshear(img, n["grid"].get("shear", 0.0) or 0.0)
        ch_o, ch_n = o["grid"].get("cell_h"), n["grid"].get("cell_h")
        oc = {c["index"]: c for c in o["columns"]}
        for c in n["columns"]:
            so = col_straddle(img_o, oc[c["index"]], ch_o) if c["index"] in oc else None
            sn = col_straddle(img_n, c, ch_n)
            if so is None or sn is None:
                continue
            rows.append((so, sn, pg, c["index"]))
            if c.get("elastic_recut"):
                recut.append((pg, c["index"], so, sn))
            if abs(so - sn) > 1e-9:
                moved += 1
    if not rows:
        print("没有可比的列"); return
    so = np.array([r[0] for r in rows]); sn = np.array([r[1] for r in rows])
    print(f"可比列 {len(rows)}，骑线比变了的 {moved}")
    print(f"  中位 {np.median(so):.3f} → {np.median(sn):.3f}"
          f"   均值 {so.mean():.3f} → {sn.mean():.3f}")
    for t in (0.6, 0.8):
        print(f"  >{t} 的列 {(so > t).sum()} → {(sn > t).sum()}")
    print(f"\n复切列 {len(recut)} 条（骑线比 旧→新）:")
    for pg, ci, x, y in sorted(recut, key=lambda r: r[2] - r[3])[:a.top]:
        print(f"  {a.book}/{pg} col{ci}: {x:.3f} → {y:.3f}")
    worse = sorted(zip(sn - so, rows), key=lambda t: -t[0])[:a.top]
    print(f"\n变差最多的列:")
    for d, (x, y, pg, ci) in worse:
        if d <= 1e-9:
            break
        print(f"  {a.book}/{pg} col{ci}: {x:.3f} → {y:.3f}  (+{d:.3f})")


if __name__ == "__main__":
    main()
