# -*- coding: utf-8 -*-
"""Step4 端格（列首/列尾）截断离线复现台：不重跑管线，在内存里跑 CharExtractor，
量「紧框相对 Step3 格内墨沿截了多少」。

    GUJI_WORKSPACE=<workspace> python scripts/step4_end_harness.py --book bxgb \\
        [--pages 3-20] [--variant NAME] [--check] [--dump base.json] [--diff base.json] [--sheet out.png]

用法：先 `--check --dump base.json` 拿基线（`--check` 核对台子与现役产物的 bbox 逐格一致，
带折线的格会不一致——run_page 里 _apply_seam 改过 bbox，不算台子错）；改代码或挂变体后
`--diff base.json` 看每一格的好转/变差，`--sheet` 把变化格出成拼图逐格看。

真值口径：Step3 格内墨的上/下沿（行墨占比 ≥ INK_ROW 的首末行）。bxgb 实测 Step3 格已包住
全部字墨（instances 金标 49 个端点格里 48 个 dropped=0），所以「紧框比墨沿靠内 >2px」= Step4
截了字。frame_residue 命中的列（格里真有框残留）单独报，不算进截断率。

2026-09-19 用它定位并修掉「尾格 22.6% 截底」（见 clustering/extractor.py FRAME_BAND_COV 注释）：
五道剥离函数逐个换恒等（VARIANTS 里的 no_* 示例）都不改变截底数，问题在条带裁切。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.steps.cell_shrink import CellShrinkParams  # noqa: E402
from open_guji_cv.clustering import extractor as EX  # noqa: E402

INK_ROW = 0.03
W = Path(os.environ.get("GUJI_WORKSPACE", "."))


def grid_of(cc, w, h, book):
    """照抄 steps/cell_shrink.py::_extract_column 的 grid 组装。"""
    pos_count: dict[int, int] = {}
    for c in cc.cells:
        pos_count[c.pos] = pos_count.get(c.pos, 0) + 1
    by_pos: dict[int, dict] = {}
    for c in cc.cells:
        d = by_pos.setdefault(c.pos, {"index": c.pos - 1, "y_top": c.y0, "y_bottom": c.y1,
                                      "type": "empty", "kinds": set(), "is_punct": False,
                                      "seam_top": None, "seam_bottom": None})
        d["kinds"].add(c.kind)
        if c.kind == "punct":
            d["is_punct"] = True
        d["y_top"], d["y_bottom"] = min(d["y_top"], c.y0), max(d["y_bottom"], c.y1)
        if c.kind != "blank":
            d["type"] = "char"
        if pos_count[c.pos] == 1:
            d["seam_top"] = c.seam_top
            d["seam_bottom"] = c.seam_bottom
    cells = [{"type": d["type"], "index": d["index"], "y_top": float(d["y_top"]),
              "y_bottom": float(d["y_bottom"]), "is_punct": d["is_punct"],
              "seam_top": d["seam_top"], "seam_bottom": d["seam_bottom"]}
             for _, d in sorted(by_pos.items())]
    x0, x1 = cc.content_x or (0.0, float(w))
    return {
        "image_size": [int(w), int(h)],
        "chars_per_line": cc.n_body_slots,
        "grid": {"shear": 0.0, "period": cc.ref_w or float(x1 - x0),
                 "cell_h": cc.period, "head_raise_rows": 0,
                 "frame_top": cc.border_top, "frame_bottom": cc.border_bottom,
                 "frame_bar_strategy": getattr(book, "frame_bar_strategy", "side_gap")},
        "columns": [{"index": cc.col, "left_x": float(x0), "right_x": float(x1),
                     "cell_left_x": float(x0), "cell_right_x": float(x1), "cells": cells}],
    }


def frame_cols(book_id: str) -> set[tuple[int, int]]:
    out = set()
    for f in glob.glob(str(W / "products" / book_id / "column_gate" / "p*.json")):
        pg = int(os.path.basename(f)[1:5])
        for c in json.load(open(f, encoding="utf-8"))["gate_manifest"].get("columns") or []:
            if any(x.startswith("frame_residue") for x in c.get("flags") or []):
                out.add((pg, c["col"]))
    return out


def _identity(name, fn):
    def patch(EX_):
        orig = getattr(EX_, name)
        setattr(EX_, name, fn)
        return lambda: setattr(EX_, name, orig)
    return patch


# 消融示例：把某一道剥离换成恒等，看它对端格截断/丢字有没有贡献
VARIANTS: dict[str, dict] = {
    "baseline": {},
    "no_debris": {"patch": _identity("strip_frame_debris", lambda patch, *a, **k: patch)},
    "no_stub": {"patch": _identity("strip_frame_stub", lambda patch, *a, **k: patch)},
    "no_carve": {"patch": _identity("carve_end_edge", lambda patch, *a, **k: patch)},
    "no_speckle": {"patch": _identity("strip_speckle_band", lambda patch, *a, **k: patch)},
    "no_maskbars": {"patch": _identity("mask_frame_bars_outside", lambda strip, *a, **k: strip)},
    "no_junk": {"patch": _identity("is_end_cell_junk", lambda *a, **k: False)},
}


def apply_variant(name: str):
    v = VARIANTS[name]
    saved = {}
    for k, val in v.get("const", {}).items():
        saved[k] = getattr(EX, k)
        setattr(EX, k, val)
    restore_fn = v["patch"](EX) if v.get("patch") else None

    def restore():
        for k, val in saved.items():
            setattr(EX, k, val)
        if restore_fn:
            restore_fn()
    return restore


def _bad(x) -> int:
    """一格的「坏度」：丢失最重，其次截顶/截底超 2px 的量，框漏进按行数加权。"""
    return ((999 if x["lost"] else 0) + max(0, x["cut_top"] - 2) + max(0, x["cut_bot"] - 2)
            + 10 * max(0, x["leak"] - 2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="bxgb")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--check", action="store_true", help="baseline 与现役产物 bbox 逐格核对")
    ap.add_argument("--dump", default=None, help="每个端格的度量写 json（供变体间 diff）")
    ap.add_argument("--diff", default=None, help="与另一份 dump 比，列出变化的格")
    ap.add_argument("--sheet", default=None, help="把变化/截断的格出成拼图")
    a = ap.parse_args()
    bk = load_book(a.book)
    st, ic = ProductStore(), ImageCache()
    p = CellShrinkParams()
    pages = bk.resolve_pages(a.pages) if a.pages else bk.all_pages()
    fcols = frame_cols(a.book)
    restore = apply_variant(a.variant)

    rows = []
    mismatch = 0
    n_checked = 0
    tiles = []
    try:
        for pg in pages:
            cells = st.read(a.book, "row_segment", page_key(pg), "cells")
            if cells is None:
                continue
            prod = st.read(a.book, "cell_shrink", page_key(pg), "char_index") if a.check else None
            for cc in cells.columns:
                if not cc.ok:
                    continue
                path = ic.get(a.book, "column_image", column_key(pg, cc.col))
                img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
                if img is None:
                    continue
                h, w = img.shape[:2]
                ex = EX.CharExtractor(padding_ratio=p.padding_ratio, min_ink_ratio=p.min_ink_ratio,
                                      strategy=p.strategy, frame_guard=p.frame_guard)
                out = ex.extract_page(img, grid_of(cc, w, h, bk), a.book, str(pg))
                by_pos = {int(inst.idx) + 1: (inst, patch) for inst, patch in out}
                n = cc.n_body_slots
                for c in cc.cells:
                    if c.sub or c.kind == "blank":
                        continue
                    end = "首" if c.slot == 1 else ("尾" if c.slot == n else None)
                    if end is None:
                        continue
                    inst, patch = by_pos.get(c.pos, (None, None))
                    if inst is None:
                        continue
                    x0, x1, y0, y1 = int(c.x0), int(c.x1), int(c.y0), int(c.y1)
                    prof = (img[y0:y1, x0:x1] < 128).mean(axis=1)
                    ink = np.where(prof >= INK_ROW)[0]
                    if len(ink) == 0:
                        continue
                    it, ib = y0 + int(ink[0]), y0 + int(ink[-1]) + 1
                    lost = (patch is None or getattr(patch, "size", 0) == 0 or inst.cell_type != "char")
                    bx = tuple(float(v) for v in inst.bbox)
                    if prod is not None:
                        pc = next((x for x in prod.columns if x.col == cc.col), None)
                        rec = next((r for r in (pc.chars if pc else []) if r.pos == c.pos and not r.sub), None)
                        if rec is not None:
                            n_checked += 1
                            if [round(v) for v in rec.bbox_col] != [round(v) for v in bx]:
                                mismatch += 1
                    cut_top = 0 if lost else int(round(bx[1] - it))
                    cut_bot = 0 if lost else int(round(ib - bx[3]))
                    leak = 0                                   # 框漏进紧框：端区满宽行数（≥0.85）
                    if not lost:
                        by0, by1 = max(0, int(bx[1])), min(h, int(bx[3]))
                        if by1 > by0:
                            pr = (img[by0:by1, x0:x1] < 128).mean(axis=1)
                            leak = int((pr >= 0.85).sum())
                    rows.append(dict(pg=pg, col=cc.col, slot=c.slot, pos=c.pos, end=end,
                                     cut_top=cut_top, cut_bot=cut_bot, lost=bool(lost), leak=leak,
                                     frame_col=(pg, cc.col) in fcols,
                                     bbox=[round(v, 1) for v in bx], ink=[it, ib], cell=[y0, y1]))
    finally:
        restore()

    s = Counter()
    for r in rows:
        key = r["end"]
        s[(key, "n")] += 1
        if r["frame_col"]:
            s[(key, "框列")] += 1
            continue
        if r["lost"]:
            s[(key, "丢失")] += 1
        elif r["cut_bot"] > 2:
            s[(key, "截底")] += 1
        elif r["cut_top"] > 2:
            s[(key, "截顶")] += 1
        if r["leak"] >= 3:
            s[(key, "框漏进")] += 1
    print(f"变体 {a.variant}  页 {len(pages)}  端格 {len(rows)}"
          + (f"  与现役 bbox 不一致 {mismatch}/{n_checked}" if a.check else ""))
    for end in ("首", "尾"):
        n = max(1, s[(end, "n")])
        print(f"  {end}: n={s[(end, 'n')]}  丢失 {s[(end, '丢失')]} ({s[(end, '丢失')] / n:.1%})  "
              f"截底 {s[(end, '截底')]} ({s[(end, '截底')] / n:.1%})  截顶 {s[(end, '截顶')]} ({s[(end, '截顶')] / n:.1%})  "
              f"框漏进 {s[(end, '框漏进')]}  [框列 {s[(end, '框列')]} 另计]")
    if a.dump:
        json.dump(rows, open(a.dump, "w", encoding="utf-8"), ensure_ascii=False)
    changed = []
    if a.diff:
        old = {(r["pg"], r["col"], r["slot"]): r for r in json.load(open(a.diff, encoding="utf-8"))}
        for r in rows:
            o = old.get((r["pg"], r["col"], r["slot"]))
            if o is None:
                continue
            if (o["lost"] != r["lost"] or abs(o["bbox"][1] - r["bbox"][1]) > 1
                    or abs(o["bbox"][3] - r["bbox"][3]) > 1):
                changed.append((o, r))
        better = sum(1 for o, r in changed if _bad(r) < _bad(o))
        worse = sum(1 for o, r in changed if _bad(r) > _bad(o))
        print(f"  与 {os.path.basename(a.diff)} 比：变化 {len(changed)} 格，好转 {better}，变差 {worse}")
        for o, r in changed:
            if _bad(r) > _bad(o):
                print(f"    变差 p{r['pg']} c{r['col']} slot{r['slot']}: 旧 cut({o['cut_top']},{o['cut_bot']}) "
                      f"lost={o['lost']} leak={o['leak']} → 新 cut({r['cut_top']},{r['cut_bot']}) "
                      f"lost={r['lost']} leak={r['leak']}")
    if a.sheet:
        pick = ([r for (_o, r) in changed] if changed
                else [r for r in rows if not r["frame_col"] and (r["lost"] or r["cut_bot"] > 2 or r["cut_top"] > 2)])
        for r in pick[:48]:
            path = ic.get(a.book, "column_image", column_key(r["pg"], r["col"]))
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            y0, y1 = r["cell"]
            a0, a1 = max(0, y0 - 8), min(img.shape[0], y1 + 25)
            t = cv2.cvtColor(img[a0:a1], cv2.COLOR_GRAY2BGR)
            for yy in (y0, y1):
                cv2.line(t, (0, yy - a0), (t.shape[1] - 1, yy - a0), (255, 0, 0), 1)
            if not r["lost"]:
                b = r["bbox"]
                cv2.rectangle(t, (int(b[0]), int(b[1]) - a0), (int(b[2]), int(b[3]) - a0), (0, 0, 255), 1)
            cv2.putText(t, f"p{r['pg']}c{r['col']}s{r['slot']}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 128, 0), 1)
            tiles.append(t)
        if tiles:
            Hh = max(t.shape[0] for t in tiles)
            Wd = max(t.shape[1] for t in tiles)
            cols = 8
            rn = (len(tiles) + cols - 1) // cols
            sheet = np.full((rn * Hh, cols * Wd, 3), 255, np.uint8)
            for i, t in enumerate(tiles):
                rr, c2 = divmod(i, cols)
                sheet[rr * Hh:rr * Hh + t.shape[0], c2 * Wd:c2 * Wd + t.shape[1]] = t
            cv2.imwrite(a.sheet, sheet)
            print("  拼图", a.sheet, sheet.shape)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
