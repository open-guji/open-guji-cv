"""生成「切分审查」工件的数据：整页叠框图 + 格位点击区 JSON。

审查对象是**裁切框对不对**（不管识别）：每页在去错切帧上画出所有
char 格的图块 bbox（绿=无 flag，橙=有 flag），empty 格画灰虚线格框
（漏切的字会表现为「字上没有框」）。输出 JSON 供 HTML 工件嵌入。

2026-08-27 加了「先看全书、再挑页细审」的第二种用法：每页附带页级
判断（页型、几列几行）与一个**免标注的疑似严重度**——直接复用本轮已经
立好的两把尺子（truncation 的 col_runs / seam 的 col_seams），同一页面
数据同时够两种审阅节奏：小图快速通览挑烂页，逐页放大细看格线。

用法：PYTHONPATH=. python scripts/build_seg_review.py \
        --pages vol01:20-45 vol02:1-24 --scale 0.5 --out review_data.json
      # 全书一册一份，小图快速过一遍：
      PYTHONPATH=. python scripts/build_seg_review.py \
        --pages vol01:1-207 --scale 0.18 --quality 35 --out vol01_full.json
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from eval_truncation import page_depths                    # noqa: E402
from eval_seam import page_seams                            # noqa: E402
from open_guji_cv.clustering.grid_segment import deshear   # noqa: E402

GREEN = (79, 125, 46)      # BGR of #2e7d4f
ORANGE = (34, 153, 210)    # BGR of #d29922
GRAY = (150, 150, 150)

PAGE_TYPE_LABEL = {
    "body": "正文", "roster": "职名", "blank": "空白",
    "cover": "封面", "label": "书签",
}
# 页级免标注严重度：直接复用本轮立的两把尺子，档位与它们的回归口径
# 一致（eval_truncation ≥10%/≥25%/≥50%、eval_seam ≥5%/≥10%/≥20%）。
# 取两者较重的那一档——两把尺子在浓墨粘连页上会给相反结论（见
# char_clustering_design.md「与 seam 打架的两页」），取重不取轻，
# 图快速过一遍时宁可多看一眼，不要漏看。
TRUNC_T = (0.50, 0.25, 0.10)
SEAM_T = (0.20, 0.10, 0.05)


def page_severity(book: str, page: str) -> tuple[int, str]:
    """(0=正常, 1=疑似, 2=较重, 3=严重), 及一句人话摘要。

    直接调用 eval_truncation.page_depths / eval_seam.page_seams——
    与两条回归闸同一份代码、同一把尺子，不另起一套算法（省得尺子
    分家、闸和这里各说各话）。"""
    depths = page_depths(book, page)
    seams = page_seams(book, page)
    n_seg = max(1, len(depths))
    n_seam = max(1, len(seams))
    t_rate = sum(1 for d in depths if d >= 0.10) / n_seg
    s_rate = sum(1 for v in seams if v >= 0.7) / n_seam
    tier = 0
    for i, t in enumerate(TRUNC_T):
        if t_rate >= t:
            tier = max(tier, 3 - i)
            break
    for i, t in enumerate(SEAM_T):
        if s_rate >= t:
            tier = max(tier, 3 - i)
            break
    label = f"截断 {t_rate:.0%}·重切缝 {s_rate:.0%}"
    return tier, label


def parse_pages(specs: list[str]) -> list[tuple[str, str]]:
    out = []
    for spec in specs:
        book, rng = spec.split(":")
        for part in rng.split(","):
            if "-" in part:
                a, b = part.split("-")
                out.extend((book, str(n)) for n in range(int(a), int(b) + 1))
            else:
                out.append((book, part))
    return out


def render_page(book: str, page: str, scale: float, quality: int):
    gp = Path("output") / book / "phase3_char_grid" / f"{page}_char_grid.json"
    if not gp.exists():
        return None
    grid = json.loads(gp.read_text(encoding="utf-8"))
    img = cv2.imread(f"output/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    shear = float(grid.get("grid", {}).get("shear", 0.0) or 0.0)
    if shear:
        img = deshear(img, shear)
    # 图块 bbox 与 flags 来自 phase4 index
    # 夹注格一格有 a/b 两个半宽实例（sub 后缀），同键收成列表全画
    flags: dict[tuple[int, int], list[str]] = {}
    bbox: dict[tuple[int, int], list[tuple[list[float], str]]] = {}
    idx_path = Path("output") / book / "phase4_chars" / "index.jsonl"
    for line in idx_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["page"] == page:
            k = (r["col"], r["idx"])
            flags[k] = r.get("flags") or []
            bbox.setdefault(k, []).append((r["bbox"], r.get("sub") or ""))

    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cells_out = []
    for col in grid.get("columns", []):
        if col.get("skipped") or not col.get("cells"):
            continue
        cno = int(col["index"])
        x0d = col.get("cell_left_x", col["left_x"])
        x1d = col.get("cell_right_x", col["right_x"])
        for i, cell in enumerate(
                c for c in col["cells"] if c.get("type") != "margin"):
            ct = cell.get("type")
            key = (cno, i)
            if ct == "char" and key in bbox:
                fl = flags.get(key, [])
                color = ORANGE if fl else GREEN
                for bb, sub in bbox[key]:
                    x0, y0, x1, y1 = [int(round(v)) for v in bb]
                    cv2.rectangle(vis, (x0, y0), (x1, y1), color, 2)
                    cells_out.append({
                        "id": f"{book}/{page}:{cno}:{i}{sub}",
                        "r": [round(v * scale, 1)
                              for v in (x0, y0, x1, y1)],
                        "f": fl})
            elif ct == "empty":
                y0, y1 = int(cell["y_top"]), int(cell["y_bottom"])
                x0, x1 = int(x0d), int(x1d)
                for xx in range(x0, x1, 12):        # 灰虚线
                    cv2.line(vis, (xx, y0), (min(xx + 6, x1), y0), GRAY, 1)
                    cv2.line(vis, (xx, y1), (min(xx + 6, x1), y1), GRAY, 1)
                cells_out.append({
                    "id": f"{book}/{page}:{cno}:{i}",
                    "r": [round(v * scale, 1) for v in (x0, y0, x1, y1)],
                    "f": ["(判空)"], "empty": True})
    small = cv2.resize(vis, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small,
                           [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None

    ptype = grid.get("page_type") or "body"
    n_cols = sum(1 for c in grid.get("columns", [])
                if c.get("cells") and not c.get("skipped"))
    n_lines = grid.get("chars_per_line")
    sev, sev_label = (0, "")
    if not grid.get("skipped") and n_cols:
        sev, sev_label = page_severity(book, page)
    return {"book": book, "page": page,
            "w": small.shape[1], "h": small.shape[0],
            "src": "data:image/jpeg;base64," +
                   base64.b64encode(buf.tobytes()).decode(),
            "cells": cells_out,
            "pt": ptype, "ptl": PAGE_TYPE_LABEL.get(ptype, ptype),
            "nc": n_cols, "nl": n_lines,
            "sev": sev, "sevl": sev_label,
            "skip": bool(grid.get("skipped"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True,
                    help="如 vol01:20-45 vol02:1-24")
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--quality", type=int, default=72)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    pages = []
    for book, page in parse_pages(args.pages):
        p = render_page(book, page, args.scale, args.quality)
        if p:
            pages.append(p)
            print(f"{book}/{page}: {len(p['cells'])} 格 "
                  f"{len(p['src']) // 1024}KB")
    Path(args.out).write_text(json.dumps(pages, ensure_ascii=False),
                              encoding="utf-8")
    total = sum(len(p["src"]) for p in pages)
    print(f"共 {len(pages)} 页，图片体积 ≈{total // 1024 // 1024}MB → {args.out}")


if __name__ == "__main__":
    main()
