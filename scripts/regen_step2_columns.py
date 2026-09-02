# -*- coding: utf-8 -*-
"""用 Step 1 的新结果重算 Step 2 的输入（单列矫正图）。

以前整页共用一个页级 `top_y = top.y_at(0)`，版框是斜的、越靠左的列偏得越多
（实测最大 54.4px，且一律偏下 → 首字被削）；抬头列更是整段被切（140~187px）。
现在 `page_column_windows()` 逐列算上下界，抬头列自动上探到抬头框外延。

弯页（`vline_segments == 3`）的界行是三段折线，`warp_column` 会按折点把列切成
横带分别射影再拼接——已验证：输出高度对得上、拼缝处无跳变、列图里界行残墨的
x 标准差 0.7~1.1px（直线页 0.6px），弯线确实被拉直了。

    python scripts/regen_step2_columns.py <book> <page> [<page> ...] [--denoise]
    python scripts/regen_step2_columns.py vol01 --gold-pages
    python scripts/regen_step2_columns.py vol01 --polyline-pages --clean   # 全册弯页
    python scripts/regen_step2_columns.py vol01,vol02 --polyline-pages --clean --jobs 8

输出：output/<book>/step2_columns/<page>/c<N>.png + <page>/windows.json
`--clean` 另出 c<N>_clean.png（`clean_column`：去噪 + 清两侧界行 + 清上下版框）。
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_guji_cv.utils.border_geometry import detect_borders
from open_guji_cv.utils.column_projection import clean_column, warp_page_columns

RAW_ROOT = Path("/home/user/rebuild_src")
FALLBACK_ROOT = Path(__file__).resolve().parent.parent / "data_full" / "zongmu"
OUT_ROOT = Path(__file__).resolve().parent.parent / "output"
GOLD_PAGES = ["137", "138", "32", "33", "49", "9", "14", "142", "24", "65", "141", "26", "47", "51"]


def _find_source(book: str, page: str) -> Path:
    """`RAW_ROOT` 是那台原始容器里的路径，这台容器上不存在——退回
    `data_full/zongmu/<book>/<page>.png`，跟 14 页金标核对过是同一张源图
    （page_size 逐位对得上），只是格式从 tif 换成了 png。"""
    tif = RAW_ROOT / book / f"{page}.tif"
    if tif.exists():
        return tif
    png = FALLBACK_ROOT / book / f"{page}.png"
    if png.exists():
        return png
    raise SystemExit(f"两个候选源都没有：{tif}  /  {png}")


def _dump_line(v) -> dict:
    """**折线的 k2/k3/y1/y2 必须一起存**——只存 {x_at_top, slope} 的话，三段页的
    边线在 windows.json 里会退化成第一段的外推直线，下游再也还原不出那条线。"""
    return dict(x_at_top=v.x_at_top, slope=v.slope,
                k2=v.k2, k3=v.k3, y1=v.y1, y2=v.y2, segments=v.segments)


def regen(book: str, page: str, expected_cols: int, denoise: bool,
          clean: bool = False, only_polyline: bool = False) -> dict | None:
    src = _find_source(book, page)
    gray = cv2.cvtColor(cv2.imread(str(src)), cv2.COLOR_BGR2GRAY)
    res = detect_borders(gray, expected_cols=expected_cols)
    if only_polyline and res.vline_segments != 3:
        return None
    out_dir = OUT_ROOT / book / "step2_columns" / page
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = dict(book=book, page=page, source_image=str(src),
                page_size=dict(width=int(gray.shape[1]), height=int(gray.shape[0])),
                top_inner=dict(y_at_right=res.top.y_at_right, slope=res.top.slope),
                bottom_inner=dict(y_at_right=res.bottom.y_at_right, slope=res.bottom.slope),
                denoised=denoise, cleaned=clean,
                vline_segments=res.vline_segments,
                bend_w80_med=res.bend_w80_med, bend_w80_max=res.bend_w80_max,
                columns=[])
    for win, img in warp_page_columns(gray, res, denoise=denoise):
        cv2.imwrite(str(out_dir / f"c{win.col}.png"), img)
        diag = None
        if clean:
            cleaned, diag = clean_column(img)
            cv2.imwrite(str(out_dir / f"c{win.col}_clean.png"), cleaned)
        meta["columns"].append(dict(
            col=win.col, file=f"c{win.col}.png",
            clean_file=f"c{win.col}_clean.png" if clean else None,
            clean_diag=None if diag is None else {
                k: (list(v) if isinstance(v, tuple) else v) for k, v in diag.items()},
            left_line=_dump_line(win.left),
            right_line=_dump_line(win.right),
            top_y=win.top_y, bottom_y=win.bottom_y,
            border_top_y=win.border_top_y, border_bottom_y=win.border_bottom_y,
            border_top_in_column=win.border_top_in_column,
            border_bottom_in_column=win.border_bottom_in_column,
            raised=win.raised, head_raise_inner_y=win.head_raise_inner_y,
            warped_size=dict(width=int(img.shape[1]), height=int(img.shape[0]))))
    (out_dir / "windows.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    return meta


def _body_pages(book: str) -> list[str]:
    """page-type 金标里 page_type == "body" 的页。"""
    pt = (Path(__file__).resolve().parent.parent.parent
          / "open-guji-dataset" / "page-type" / "expected.json")
    rows = json.loads(pt.read_text(encoding="utf-8"))
    return [r["page"] for r in rows if r["book"] == book and r.get("page_type") == "body"]


def _one(args):
    book, pg, cols, denoise, clean, only_poly = args
    try:
        return book, pg, regen(book, pg, cols, denoise, clean, only_poly)
    except SystemExit as e:                      # 源图缺失等，跳过不要拖垮整批
        return book, pg, {"error": str(e)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("book", help="书名；批量时可用逗号分隔多册")
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--gold-pages", action="store_true", help="用 border-detection 金标那 14 页")
    ap.add_argument("--polyline-pages", action="store_true",
                    help="扫全册正文页，只处理 Step1 判为三段折线的页")
    ap.add_argument("--cols", type=int, default=9)
    ap.add_argument("--denoise", action="store_true")
    ap.add_argument("--clean", action="store_true",
                    help="另出 c<N>_clean.png：去噪 + 清两侧界行 + 清上下版框")
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    books = [b.strip() for b in a.book.split(",") if b.strip()]

    jobs = []
    for bk in books:
        if a.polyline_pages:
            pgs = _body_pages(bk)
        elif a.gold_pages:
            pgs = GOLD_PAGES
        else:
            pgs = a.pages
        if not pgs:
            ap.error("给页号，或者 --gold-pages / --polyline-pages")
        jobs += [(bk, pg, a.cols, a.denoise, a.clean, a.polyline_pages) for pg in pgs]

    print(f"待处理 {len(jobs)} 页（{', '.join(books)}）"
          + ("，只留三段折线页" if a.polyline_pages else "")
          + f"，{a.jobs} 并行…", flush=True)
    n_raised = n_done = n_skip = n_err = 0
    done_pages = []
    if a.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        it = ProcessPoolExecutor(max_workers=a.jobs).map(_one, jobs, chunksize=1)
    else:
        it = map(_one, jobs)
    for i, (bk, pg, m) in enumerate(it, 1):
        if m is None:
            n_skip += 1
        elif "error" in m:
            n_err += 1
            print(f"  !! {bk}/{pg}: {m['error']}", flush=True)
        else:
            n_done += 1
            done_pages.append(f"{bk}/{pg}")
            r = [c["col"] for c in m["columns"] if c["raised"]]
            n_raised += len(r)
            print(f"{bk}/{pg}: {len(m['columns'])} 列  seg={m['vline_segments']}"
                  f"  w80={m['bend_w80_med']}"
                  + (f"  抬头列 {r}" if r else ""), flush=True)
        if a.polyline_pages and i % 25 == 0:
            print(f"  … {i}/{len(jobs)} 页，已出 {n_done}", flush=True)
    print(f"\n完成：处理 {n_done} 页" + (f"，跳过直线页 {n_skip}" if n_skip else "")
          + (f"，出错 {n_err}" if n_err else "") + f"，抬头列共 {n_raised} 个")
    if a.polyline_pages:
        out = OUT_ROOT / "polyline_pages.json"
        out.write_text(json.dumps(sorted(done_pages), ensure_ascii=False, indent=1) + "\n")
        print(f"三段折线页清单写出 {out}")
