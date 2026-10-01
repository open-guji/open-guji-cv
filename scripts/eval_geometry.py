"""版面几何 benchmark（v2 链口径）：界行有没有被列框圈进去 + 列带里界行还歪多少。

2026-09-30 M1·D 道改版：
  · 原先读已退役 v1 链 `./output/<册>/phase3_char_grid`（列框 left_x/right_x + shear）和
    `output/<册>/<页>.png`——云端没有，静默扫到 0 页（空跑）；
  · 现读 v2 Step2 产物 `column_windows`（每列 left_line/right_line/band，三段折线页分带），
    经 `ColumnMapper`（与 Step3 `quad_page` 同一映射）回到**原图**，在金标三个高度上取列带 [左,右]；
  · 金标已迁到原图帧（artifacts/m1_gold/geometry/MIGRATION.md）。
指标定义与差异见 open_guji_cv/clustering/geometry_eval.py 的「v2 链口径」一节。

用法（需要 GUJI_WORKSPACE / GUJI_PRODUCTS_DIR，产物缺了用 `eval --from-raw` 补）：
    python scripts/eval_geometry.py ../open-guji-dataset/page-geometry [--json-out r.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from open_guji_cv.clustering.geometry_eval import (_column_interval_fn,
                                                   evaluate_v2, format_report)
from open_guji_cv.clustering.page_geometry import PageGeometry


def _raw_image(book: str, page: str):
    """原图：书定义里的 raw_dir / raw_pattern（工作区 data_full 下）。"""
    from open_guji_cv.core.book import load_book
    p = load_book(book).raw_path(int(page))
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.steps._warpmap import ColumnMapper

    store = ProductStore()
    pairs, skipped = [], []
    for f in sorted(Path(args.dataset, "samples").glob("*.json")):
        g = PageGeometry.load(f)
        if g.coordinate_frame != "raw_page_px@top-left":
            skipped.append((g.book, g.page, "金标不在原图帧（未迁移）"))
            continue
        wins = store.read(g.book, "column_warp", page_key(int(g.page)), "column_windows")
        if wins is None:
            skipped.append((g.book, g.page, "缺 Step2 产物 column_windows"))
            continue
        gray = _raw_image(g.book, g.page)
        if gray is None:
            skipped.append((g.book, g.page, "原图缺失"))
            continue
        if gray.shape[1] != g.image_size["width"] or gray.shape[0] != g.image_size["height"]:
            skipped.append((g.book, g.page, f"原图尺寸 {gray.shape[::-1]} ≠ 金标 {g.image_size}"))
            continue
        fns = []
        for c in wins.columns:
            m = ColumnMapper(wins.page_size[0], c.left_line.to_vline(), c.right_line.to_vline(),
                             c.top_y, c.bottom_y)
            fns.append(_column_interval_fn(m, c.band, wins.page_size[0]))
        pairs.append((g, fns, gray))
    if skipped:
        print(f"（{len(skipped)} 页跳过：" + "；".join(f"{b}/{p} {why}" for b, p, why in skipped) + "）")
    if not pairs:
        print("0 页可评（产物/原图都缺）——这是空跑，不是通过")
        raise SystemExit(2)
    report = evaluate_v2(pairs)
    report["skipped"] = [{"book": b, "page": p, "why": w} for b, p, w in skipped]
    print(format_report(report))
    o = report["overall"]
    if "clearance_median" in o:
        print(f"净空（界行点到最近列带边缘，负=落进带内；诊断）：中位 {o['clearance_median']}px / "
              f"5分位 {o['clearance_p5']}px / 最小 {o['clearance_min']}px；落进带内的采样点 {o['n_samples_inside_col']}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
