#!/usr/bin/env python3
"""调查脚本：直线切 vs 曲线切 全册 A/B（P2 #12）。

对每个「高 >SPLIT_H_RATIO×格高」连通体 × 它跨过的格线，比较三个量：

  resolved   切后不再有连通体在该格线两侧各有 ≥100px 墨（粘连已解开）
  damage     该刀清掉的本连通体像素数（刀口墨损，直刀=整行、曲刀=沿路径）
  cut_dist   刀口（均值）到格线的距离

用法：PYTHONPATH=. python scripts/research_split_ab.py output/vol01
"""
import json, sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from open_guji_cv.clustering import extractor as E
from research_split_scan import prep_strip


def residual(binary, g, x0, x1):
    """格线 g 两侧各 ≥100px 墨的连通体仍存在？（只看原组件 x 范围附近）"""
    n, lab, st, _ = cv2.connectedComponentsWithStats(binary, 8)
    for k in range(1, n):
        x, y, cw, ch, a = st[k]
        if a < 250 or not (y < g < y + ch):
            continue
        if x + cw < x0 - 5 or x > x1 + 5:
            continue
        comp = lab == k
        gi = int(g)
        above = int(comp[:max(0, gi - 2)].sum())
        below = int(comp[gi + 2:].sum())
        if above >= 100 and below >= 100:
            return True
    return False


def main():
    book = Path(sys.argv[1])
    grid_dir = book / "phase3_char_grid"
    src = E.CharExtractor._resolve_source_dir(book)
    agg = Counter()
    dmg_s, dmg_c, dist_s, dist_c = [], [], [], []
    rows = []
    for gf in sorted(grid_dir.glob("*_char_grid.json")):
        page = gf.stem.replace("_char_grid", "")
        img_path = E.CharExtractor._find_page_image(src, page)
        if img_path is None:
            continue
        img = E.imread(str(img_path))
        if img is None:
            continue
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        grid = json.load(open(gf, encoding="utf-8"))
        shear = float(grid.get("grid", {}).get("shear", 0.0) or 0.0)
        if shear:
            img = E._deshear(img, shear)
        for col in grid.get("columns", []):
            r = prep_strip(img, grid, col)
            if r is None:
                continue
            binary, local, cell_h, sx0, sy0, col_w, _ = r
            n, lab, st, _ = cv2.connectedComponentsWithStats(binary, 8)
            lines = [t for _i, t, _b in local[1:]]
            cand = []
            for k in range(1, n):
                x, y, cw, ch, a = st[k]
                if a < E.MIN_COMP_AREA_RATIO * cell_h * col_w:
                    continue
                if ch <= E.SPLIT_H_RATIO * cell_h:
                    continue
                if ch > E.RULE_H_RATIO * cell_h and cw <= E.RULE_W_RATIO * col_w:
                    continue
                for g in lines:
                    if y < g < y + ch:
                        cand.append((k, g, x, y, cw, ch))
            if not cand:
                continue
            bs = E._split_touching(binary, local, cell_h, col_w)
            bc = E._split_touching_curve(binary, local, cell_h, col_w)
            for k, g, x, y, cw, ch in cand:
                rs = residual(bs, g, x, x + cw)
                rc = residual(bc, g, x, x + cw)
                comp = lab == k
                ds = int((comp & (bs == 0)).sum())
                dc = int((comp & (bc == 0)).sum())
                agg["events"] += 1
                agg["resolved_straight"] += (not rs)
                agg["resolved_curve"] += (not rc)
                agg["both"] += (not rs) and (not rc)
                agg["only_curve"] += rs and (not rc)
                agg["only_straight"] += (not rs) and rc
                rows.append({"page": page, "col": int(col["index"]),
                             "g": float(g + sy0), "h_ratio": round(ch / cell_h, 2),
                             "res_straight": bool(rs), "res_curve": bool(rc),
                             "dmg_straight_px": ds, "dmg_curve_px": dc})
    print(dict(agg))
    print("resolved: straight %.1f%%  curve %.1f%%" % (
        100 * agg["resolved_straight"] / agg["events"],
        100 * agg["resolved_curve"] / agg["events"]))
    json.dump(rows, open("/tmp/guji_taskB/ab_full.json", "w"))
    print("saved /tmp/guji_taskB/ab_full.json")


if __name__ == "__main__":
    main()
