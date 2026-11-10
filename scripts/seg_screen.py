#!/usr/bin/env python3
"""切分筛查（A22 F4①②、F7、F8，2026-11-10）：只读本机产物与列图，各书通用，列出要看图的列与页。

判据在 `open_guji_cv/eval/seg_screen.py` 模块头。不改产物、不进指纹。

用法（GUJI_WORKSPACE 指向书的工作区，产物在本机）：

    python scripts/seg_screen.py --books 04 06 --out <报告目录>
    python scripts/seg_screen.py --books 001 002 --seal-blank     # 加 F8：列出 seed_admit 会按印框记空的格（要原图）

输出：每项一张 TSV（edge_ink.tsv、colnet_page.tsv、layout_col_shift.tsv、pitch_free_ignored.tsv、seal_blank.tsv）
和 summary.md（逐册计数）。要看图就把 TSV 交 `guji-manager review-pages build`。
格位表取本册 row_segment 的 `layout_prior` 参数（册配置里写的那份）；没开的册跳过 ②b 与 F7。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHECKS = ("edge_ink", "colnet_page", "layout_col_shift", "pitch_free_ignored", "seal_blank")


def _engine(book: str):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.core.pipeline import default_pipeline_id, load_pipeline
    bk = load_book(book)
    return Engine(bk, load_pipeline(default_pipeline_id(bk)), log=lambda s: None)


def screen_book(book: str, pages: set[int] | None, seal_blank: bool, rows: dict[str, list], counts: dict):
    import cv2

    import open_guji_cv.products.kinds  # noqa: F401
    from open_guji_cv.core.spec import column_key, page_key
    from open_guji_cv.eval import seg_screen as ss
    from open_guji_cv.steps.row_segment import RowSegmentStep, load_layout

    eng = _engine(book)
    ctx, store = eng.ctx, eng.store
    rs = ctx.params_for(RowSegmentStep())
    layout = {}
    if getattr(rs, "layout_prior", ""):
        try:
            layout = load_layout(rs.layout_prior, book)
        except FileNotFoundError as e:
            print(f"⚠️ {book}：{e}，跳过 ②b／F7", file=sys.stderr)
    keys = sorted(p.stem for p in store.step_dir(book, "row_segment").glob("p[0-9]*.json"))
    c = counts.setdefault(book, {k: 0 for k in CHECKS} | {"pages": 0})
    for key in keys:
        page = int(key[1:])
        if pages and page not in pages:
            continue
        cells = store.read(book, "row_segment", key, "cells")
        if cells is None:
            continue
        c["pages"] += 1
        gate = store.read(book, "column_gate", page_key(page), "gate_manifest")
        if gate is not None:
            for hit in ss.colnet_page(gate):
                rows["colnet_page"].append((book, page, hit["col"], hit["ratio"], f"带宽 {hit['width']}px"))
            c["colnet_page"] += bool(ss.colnet_page(gate))
        lay_page = {col: r for (pg, col), r in layout.items() if pg == page}
        sh = ss.layout_col_shift(cells, lay_page)
        if sh:
            rows["layout_col_shift"].append((book, page, "", sh["shift"],
                                             f"不挪对上 {sh['match0']}/{sh['cols']}，挪后 {sh['match']}"))
            c["layout_col_shift"] += 1
        for cc in cells.columns:
            if not cc.ok:
                continue
            if ss.pitch_free_ignored(cc, lay_page.get(cc.col)):
                rows["pitch_free_ignored"].append((book, page, cc.col, "", "表写 pitch: free，选中挤格补线格网"))
                c["pitch_free_ignored"] += 1
            if "manual_cells" in cc.flags or "roster" in cc.flags:
                continue                  # 人定字框、职名列不按格网查端外墨
            p = ctx.cache.get(book, "column_image", column_key(page, cc.col))
            if p is None:
                continue
            gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            e = ss.edge_ink(gray, cc)
            if e:
                rows["edge_ink"].append((book, page, cc.col, max(e["top"], e["bottom"]),
                                         f"上 {e['top']} 行、下 {e['bottom']} 行有墨（格高 {e['period']}）"))
                c["edge_ink"] += 1
        if seal_blank:
            from open_guji_cv.steps.occlusion import page_seal_blank
            from open_guji_cv.steps.seed_admit import SeedAdmitStep
            for (col, slot, sub), info in sorted(page_seal_blank(ctx, page, ctx.params_for(SeedAdmitStep())).items()):
                rows["seal_blank"].append((book, page, col, f"{slot}{sub}", str(info)[:80]))
                c["seal_blank"] += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books", nargs="+", required=True)
    ap.add_argument("--pages", help="只查这些页（逗号分隔，各册通用）")
    ap.add_argument("--seal-blank", action="store_true", help="加 F8（要原图，慢）")
    ap.add_argument("--out", default="seg_screen_out")
    a = ap.parse_args(argv)
    pages = {int(x) for x in a.pages.split(",")} if a.pages else None
    rows: dict[str, list] = {k: [] for k in CHECKS}
    counts: dict = {}
    for b in a.books:
        screen_book(b, pages, a.seal_blank, rows, counts)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for k, rs in rows.items():
        if k == "seal_blank" and not a.seal_blank:
            continue
        with open(out / f"{k}.tsv", "w", encoding="utf-8") as f:
            f.write("book\tpage\tcol\tvalue\tnote\n")
            f.writelines("\t".join(map(str, r)) + "\n" for r in rs)
    hdr = ["册", "页数", *[k for k in CHECKS if k != "seal_blank" or a.seal_blank]]
    lines = ["# 切分筛查", "", "| " + " | ".join(hdr) + " |", "|" + " --- |" * len(hdr)]
    for b, c in counts.items():
        lines.append("| " + " | ".join([b, str(c["pages"]), *[str(c[k]) for k in hdr[2:]]]) + " |")
    lines += ["", "edge_ink、pitch_free_ignored 按列计；colnet_page、layout_col_shift 按页计；seal_blank 按格计。"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
