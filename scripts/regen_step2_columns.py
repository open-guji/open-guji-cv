# -*- coding: utf-8 -*-
"""用 Step 1 的新结果重算 Step 2 的输入（单列矫正图）。

以前整页共用一个页级 `top_y = top.y_at(0)`，版框是斜的、越靠左的列偏得越多
（实测最大 54.4px，且一律偏下 → 首字被削）；抬头列更是整段被切（140~187px）。
现在 `page_column_windows()` 逐列算上下界，抬头列自动上探到抬头框外延。

    python scripts/regen_step2_columns.py <book> <page> [<page> ...] [--denoise]
    python scripts/regen_step2_columns.py vol01 --gold-pages

输出：output/<book>/step2_columns/<page>/c<N>.png + <page>/windows.json
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_guji_cv.utils.border_geometry import detect_borders
from open_guji_cv.utils.column_projection import warp_page_columns

RAW_ROOT = Path("/home/user/rebuild_src")
OUT_ROOT = Path(__file__).resolve().parent.parent / "output"
GOLD_PAGES = ["137", "138", "32", "33", "49", "9", "14", "142", "24", "65", "141", "26", "47", "51"]


def regen(book: str, page: str, expected_cols: int, denoise: bool) -> dict:
    src = RAW_ROOT / book / f"{page}.tif"
    gray = cv2.cvtColor(cv2.imread(str(src)), cv2.COLOR_BGR2GRAY)
    res = detect_borders(gray, expected_cols=expected_cols)
    out_dir = OUT_ROOT / book / "step2_columns" / page
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = dict(book=book, page=page, source_image=str(src),
                page_size=dict(width=int(gray.shape[1]), height=int(gray.shape[0])),
                top_inner=dict(y_at_right=res.top.y_at_right, slope=res.top.slope),
                bottom_inner=dict(y_at_right=res.bottom.y_at_right, slope=res.bottom.slope),
                denoised=denoise, columns=[])
    for win, img in warp_page_columns(gray, res, denoise=denoise):
        cv2.imwrite(str(out_dir / f"c{win.col}.png"), img)
        meta["columns"].append(dict(
            col=win.col, file=f"c{win.col}.png",
            left_line=dict(x_at_top=win.left.x_at_top, slope=win.left.slope),
            right_line=dict(x_at_top=win.right.x_at_top, slope=win.right.slope),
            top_y=win.top_y, bottom_y=win.bottom_y,
            border_top_y=win.border_top_y, border_bottom_y=win.border_bottom_y,
            border_top_in_column=win.border_top_in_column,
            border_bottom_in_column=win.border_bottom_in_column,
            raised=win.raised, head_raise_outer_y=win.head_raise_outer_y,
            warped_size=dict(width=int(img.shape[1]), height=int(img.shape[0]))))
    (out_dir / "windows.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--gold-pages", action="store_true", help="用 border-detection 金标那 14 页")
    ap.add_argument("--cols", type=int, default=9)
    ap.add_argument("--denoise", action="store_true")
    a = ap.parse_args()
    pages = GOLD_PAGES if a.gold_pages else a.pages
    if not pages:
        ap.error("给页号，或者 --gold-pages")
    n_raised = 0
    for pg in pages:
        m = regen(a.book, pg, a.cols, a.denoise)
        r = [c["col"] for c in m["columns"] if c["raised"]]
        n_raised += len(r)
        print(f"{a.book}/{pg}: {len(m['columns'])} 列"
              + (f"，抬头列 {r}（多矫正 "
                 + ", ".join(f"{c['border_top_in_column']:.0f}px" for c in m["columns"] if c["raised"])
                 + "）" if r else ""), flush=True)
    print(f"\n完成，抬头列共 {n_raised} 个")
