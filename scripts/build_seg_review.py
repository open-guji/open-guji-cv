"""生成「切分审查」工件的数据：整页叠框图 + 格位点击区 JSON。

审查对象是**裁切框对不对**（不管识别）：每页在去错切帧上画出所有
char 格的图块 bbox（绿=无 flag，橙=有 flag），empty 格画灰虚线格框
（漏切的字会表现为「字上没有框」）。输出 JSON 供 HTML 工件嵌入。

用法：PYTHONPATH=. python scripts/build_seg_review.py \
        --pages vol01:20-45 vol02:1-24 --scale 0.5 --out review_data.json
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.grid_segment import deshear

GREEN = (79, 125, 46)      # BGR of #2e7d4f
ORANGE = (34, 153, 210)    # BGR of #d29922
GRAY = (150, 150, 150)


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
    flags: dict[tuple[int, int], list[str]] = {}
    bbox: dict[tuple[int, int], list[float]] = {}
    idx_path = Path("output") / book / "phase4_chars" / "index.jsonl"
    for line in idx_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["page"] == page:
            flags[(r["col"], r["idx"])] = r.get("flags") or []
            bbox[(r["col"], r["idx"])] = r["bbox"]

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
                x0, y0, x1, y1 = [int(round(v)) for v in bbox[key]]
                fl = flags.get(key, [])
                color = ORANGE if fl else GREEN
                cv2.rectangle(vis, (x0, y0), (x1, y1), color, 2)
                cells_out.append({
                    "id": f"{book}/{page}:{cno}:{i}",
                    "r": [round(v * scale, 1) for v in (x0, y0, x1, y1)],
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
    return {"book": book, "page": page,
            "w": small.shape[1], "h": small.shape[0],
            "src": "data:image/jpeg;base64," +
                   base64.b64encode(buf.tobytes()).decode(),
            "cells": cells_out}


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
