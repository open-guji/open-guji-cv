# -*- coding: utf-8 -*-
"""列首／列尾字框「压框线」率：末/首个字的紧框越过内框细线的列占比（overview#66，S 道 2026-09-28）。

    python scripts/eval_end_rule.py --book v006 [--pages 3-80] [--json out.json] [--list]

## 量法

在**列图**上找列端的内框细线：列尾看最后 12% 行、列首看最前 12% 行，文字窗取列图宽的
5%–95%，横向闭合 9px（接虚线断口）后覆盖 ≥0.75 的行连成段，取**最靠里**的一段半峰厚 ≤12px
的当内框线，记它的内沿。末（首）个 `cell_type=="char"` 的紧框 `bbox_col` 越过内沿 ≥2px
记「压线」。**线找不到的列不计**（分母=找到线的列，随书变，报数必须带分母）。

与 `eval_frame_residue.py` 的区别：那把尺子按 Step2 `column_border_trim` 自己的判档分桶、
量的是**列图**端部削没削干净（四庫口径）；这把量的是 **Step4 紧框**有没有把线装进字块——
全唐文的列图端部本来就留着内框线（Step2 按设计不削），问题出在 Step4 裁紧时把线当成了字。

## 已知局限（别当缺陷数用）

- 线与字身粘连、或线本身断成几截覆盖不到 0.75 的列，量不到（漏计，偏乐观）；
- v006 列图中部最宽的字横笔闭合后覆盖 ≤0.73，所以 0.75 门槛在端区 12% 里偶有把宽底横当线的可能
  （偏悲观）。v006 目视 60 例未见，但没做全量人裁。
"""
from __future__ import annotations

import argparse
import json
import sys
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

END_ZONE = 0.12
COV_T = 0.75
MAX_T = 12
OVER_PX = 2


def _hclose(b: np.ndarray, w: int = 9) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (w, 1))
    return cv2.morphologyEx(b.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0


def find_rule(img: np.ndarray, bottom: bool) -> int | None:
    """列图端部内框细线的**内沿**行号（列图坐标）；找不到返回 None。"""
    H, W = img.shape
    z = int(END_ZONE * H)
    x0, x1 = int(0.05 * W), int(0.95 * W)
    reg = img[H - z:, x0:x1] if bottom else img[:z, x0:x1][::-1]
    cov = _hclose(reg < 128).mean(axis=1)
    ys = np.flatnonzero(cov >= COV_T)
    if not ys.size:
        return None
    runs = []
    a = p = int(ys[0])
    for y in ys[1:]:
        y = int(y)
        if y == p + 1:
            p = y
            continue
        runs.append((a, p))
        a = p = y
    runs.append((a, p))
    thin = [(a, e) for a, e in runs if e - a + 1 <= MAX_T]
    if not thin:
        return None
    a, _e = thin[0]                      # reg 已翻成「内在前」：第一段即最靠里
    return H - z + a if bottom else z - 1 - a


def measure(book: str, pages: list[int], store: ProductStore, cache: ImageCache) -> list[dict]:
    out: list[dict] = []
    for pg in pages:
        ci = store.read(book, "cell_shrink", page_key(pg), "char_index")
        if ci is None:
            continue
        for cc in ci.columns:
            chars = [c for c in (cc.chars or []) if c.cell_type == "char" and not c.sub]
            if not cc.ok or not chars:
                continue
            p = cache.get(book, "column_image", column_key(pg, cc.col))
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p else None
            if img is None:
                continue
            for end, bottom in (("tail", True), ("head", False)):
                yl = find_rule(img, bottom)
                if yl is None:
                    continue
                c = max(chars, key=lambda c: c.pos) if bottom else min(chars, key=lambda c: c.pos)
                over = (c.bbox_col[3] - yl) if bottom else (yl - c.bbox_col[1])
                out.append({"page": pg, "col": cc.col, "slot": c.slot, "end": end, "rule": int(yl),
                            "bbox": list(c.bbox_col), "over": float(over), "hit": bool(over >= OVER_PX)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", default="all")
    ap.add_argument("--json", default=None)
    ap.add_argument("--list", action="store_true", help="列出压线的格")
    a = ap.parse_args()
    bk = load_book(a.book)
    rows = measure(a.book, bk.resolve_pages(a.pages), ProductStore(), ImageCache())
    rep = {"book": a.book}
    for end in ("tail", "head"):
        rs = [r for r in rows if r["end"] == end]
        h = sum(r["hit"] for r in rs)
        rep[end] = {"n_rule_found": len(rs), "hit": h, "rate": round(h / len(rs), 4) if rs else None}
        print(f"{a.book} 列{'尾' if end == 'tail' else '首'}：压线 {h}/{len(rs)}"
              + (f" = {h / len(rs):.1%}" if rs else ""))
    if a.list:
        for r in rows:
            if r["hit"]:
                print(f"  p{r['page']} c{r['col']} s{r['slot']} {r['end']} 越线 {r['over']:.0f}px")
    if a.json:
        Path(a.json).write_text(json.dumps({"report": rep, "rows": rows}, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
