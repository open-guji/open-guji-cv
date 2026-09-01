#!/usr/bin/env python3
"""调查脚本：全册扫描 _split_touching 的工作面（P2 #12 曲线切分前置量面）。

对每页每列复刻 extract_page 的条带准备（bands 抹墙 + 版框横条掩蔽 +
二值化 + 剔线），然后对高 >SPLIT_H_RATIO×格高 的连通体逐格线复刻
_split_touching 的判据，分类统计：

  cut_ok          找到合格颈部并下刀
  no_thin         窗内没有任何行细过 NECK_ABS（真·重度粘连/竖线贯穿）
  filtered_piece  有细行但全被 MIN_PIECE/MIN_TAIL 过滤（修/集 类病灶）
  window_empty    搜索窗为空（组件端部离格线太近）
  merged_hard     高 >MERGE_H_RATIO×格高，直接进硬切通道（不试颈部）

用法：PYTHONPATH=. python scripts/research_split_scan.py output/vol01 [--json out.json]
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_guji_cv.clustering import extractor as E


def prep_strip(page_img, grid, col):
    """复刻 extract_page 的条带准备，返回 (binary, local_cells, cell_h, sx0, sy0, col_w)。"""
    cells = [c for c in col.get("cells", []) if c.get("type") == "char"]
    if not cells:
        return None
    heights = [float(c["y_bottom"]) - float(c["y_top"]) for c in cells]
    cell_h = float(np.median(heights))
    gl, gr = col.get("cell_left_x"), col.get("cell_right_x")
    if gl is None or gr is None:
        col_w0 = float(col["right_x"]) - float(col["left_x"])
        shrink = min(col_w0 * 0.03, 4.0)
        gl, gr = float(col["left_x"]) + shrink, float(col["right_x"]) - shrink
    img_h, img_w = page_img.shape[:2]
    sx0 = int(round(max(0.0, float(gl))))
    sx1 = int(round(min(float(img_w), float(gr))))
    pad = cell_h * E.PADDING_RATIO
    sy0 = int(round(max(0.0, min(float(c["y_top"]) for c in cells) - pad)))
    sy1 = int(round(min(float(img_h), max(float(c["y_bottom"]) for c in cells) + pad)))
    if sx1 <= sx0 or sy1 <= sy0:
        return None
    strip = page_img[sy0:sy1, sx0:sx1].copy()
    bands = col.get("cell_bands")
    if bands:
        for ya, yb, blx, brx in bands:
            ra = max(0, int(round(ya)) - sy0)
            rb = min(strip.shape[0], int(round(yb)) - sy0)
            if rb <= ra:
                continue
            ca = max(0, int(round(blx)) - sx0)
            cb = min(strip.shape[1], int(round(brx)) - sx0)
            if ca > 0:
                strip[ra:rb, :ca] = 255
            if cb < strip.shape[1]:
                strip[ra:rb, cb:] = 255
    local = [(int(c["index"]), float(c["y_top"]) - sy0,
              float(c["y_bottom"]) - sy0) for c in cells]
    strip = E.mask_frame_bars_outside(
        strip, local, int(round(float(col["left_x"]))) - sx0,
        int(round(float(col["right_x"]))) - sx0, cell_h)
    binary = E._strip_lines(E._column_binary(strip), cell_h)
    return binary, local, cell_h, sx0, sy0, float(sx1 - sx0), strip


def scan_column(binary, cells, cell_h, col_w):
    """对一列复刻 _split_touching 的判据，返回事件列表。"""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    lines = [top for _i, top, _b in cells[1:]]
    win = E.SPLIT_WIN * cell_h
    events = []
    for k in range(1, n):
        x, y, cw, ch, area = stats[k]
        if area < E.MIN_COMP_AREA_RATIO * cell_h * col_w:
            continue
        if ch <= E.SPLIT_H_RATIO * cell_h:
            continue
        if ch > E.RULE_H_RATIO * cell_h and cw <= E.RULE_W_RATIO * col_w:
            continue  # 界行竖线，_assign_column 会丢弃
        merged_hard = bool(ch > E.MERGE_H_RATIO * cell_h)
        comp = labels == k
        prof = comp.sum(axis=1)
        # 只考察组件实际跨过的格线
        touched = [g for g in lines if y < g < y + ch]
        for g in touched:
            lo = int(max(y + 0.2 * cell_h, g - win))
            hi = int(min(y + ch - 0.2 * cell_h, g + win, y + E.FIT_RATIO * cell_h))
            ev = {"g": float(g), "comp": [int(x), int(y), int(cw), int(ch)],
                  "h_ratio": round(ch / cell_h, 2), "merged_hard": merged_hard}
            if hi <= lo:
                ev["cat"] = "window_empty"
                events.append(ev)
                continue
            thin = np.flatnonzero(prof[lo:hi] <= E.NECK_ABS * col_w) + lo
            if thin.size == 0:
                ev["cat"] = "no_thin"
                events.append(ev)
                continue
            ok = thin[(thin - y >= E.MIN_PIECE * cell_h)
                      & (y + ch - thin >= E.MIN_TAIL * cell_h)]
            if ok.size == 0:
                ev["cat"] = "filtered_piece"
            else:
                r = int(ok[np.argmin(np.abs(ok - g))])
                ev["cat"] = "cut_ok"
                ev["cut"] = r
                ev["cut_dist_to_g"] = round(abs(r - g), 1)
                # 有没有更贴格线、但被 MIN_PIECE 拦下的细行？
                better = thin[np.abs(thin - g) < abs(r - g) - 2]
                ev["blocked_better"] = bool(better.size > 0)
            events.append(ev)
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    book = Path(args.book_dir)
    grid_dir = book / "phase3_char_grid"
    src = E.CharExtractor._resolve_source_dir(book)
    from collections import Counter
    cats = Counter()
    all_events = []
    n_pages = 0
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
            binary, local, cell_h, sx0, sy0, col_w, _strip = r
            for ev in scan_column(binary, local, cell_h, col_w):
                ev.update(page=page, col=int(col["index"]),
                          sx0=sx0, sy0=sy0, cell_h=round(cell_h, 1))
                key = ("merged_hard_" if ev["merged_hard"] else "") + ev["cat"]
                cats[key] += 1
                all_events.append(ev)
        n_pages += 1
    print(f"pages={n_pages}  events={len(all_events)}")
    for k, v in cats.most_common():
        print(f"  {k:28s} {v}")
    nb = sum(1 for e in all_events if e.get("blocked_better"))
    print(f"  cut_ok 中被 MIN_PIECE 挡住更贴格线细行的: {nb}")
    if args.json:
        json.dump(all_events, open(args.json, "w"), ensure_ascii=False)
        print("saved", args.json)


if __name__ == "__main__":
    main()
