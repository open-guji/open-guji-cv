# -*- coding: utf-8 -*-
"""四庫 v1 旧管线刻例 → 现在的格：按形状找，不再按「格号 = idx+1」猜（字形库 08，2026-09-26）。

    GUJI_WORKSPACE=<四庫书目录> PYTHONPATH=. python scripts/glyph_v1_map.py <out.jsonl> [--pages 1-50]

v1 的 id 是 `<册>:页:列:idx`（idx 从 0、还数进了页边格），v2 起是 slot（从 1）。多数页
slot = idx+1，但重切、行相位修正之后会整列错开，靠猜会对错格。这里拿库里存的 v1 图块，
在同页、同列 ±1、格号 idx−3…idx+5 的现有字块里找形状最像的：

- ``exact``  逐像素几乎一样（≥0.995）
- ``match``  ≥0.92 且比第二名高 0.03
- ``weak``   有候选但不够把握（best 记下来）
- ``nocells`` 这一页没有现役字框产物（字块缺了就现算，`ctx.image` 走 materialize）

输出供 `glyph_crosscheck.py --v1-map` 用：对 v1 刻例的一切对账都改走这张表。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.canonical import to_canonical  # noqa: E402
from open_guji_cv.clustering.glyph_db import _unpng  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402
from open_guji_cv.core.workspace import glyph_db_path  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.utils.binarized import binarize_page  # noqa: E402

TH, MARGIN, EXACT = 0.92, 0.03, 0.995


def main() -> int:
    out = Path(sys.argv[1])
    lo, hi = 0, 10 ** 6
    if "--pages" in sys.argv:
        a, _, b = sys.argv[sys.argv.index("--pages") + 1].partition("-")
        lo, hi = int(a), int(b or a)
    c = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
    rows = c.execute(
        "SELECT i.instance_id, i.label, d.data FROM instances i JOIN derived d "
        "ON d.instance_id=i.instance_id AND d.kind='norm' "
        "JOIN sources s ON s.source_id=i.source_id WHERE s.pipeline_version='v1'").fetchall()
    import open_guji_cv.steps  # noqa: F401  注册各步，materialize 才找得到生产者
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.store import ProductStore
    st, cache = ProductStore(), ImageCache()
    ctxs: dict[str, RunContext] = {}
    cells_of: dict[tuple, list] = {}          # (册, 页) → [(列, 格号, 子格, patch_key)]
    norm_cache: dict[tuple, object] = {}
    n = 0

    def page_cells(b, pg):
        k = (b, pg)
        if k not in cells_of:
            ci = st.read(b, "cell_shrink", page_key(pg), "char_index")
            cells_of[k] = [] if ci is None else [
                (cc.col, r.slot, r.sub or "", r.patch_key)
                for cc in ci.columns if cc.ok for r in cc.chars
                if r.cell_type == "char" and r.patch_key]
        return cells_of[k]

    def cur_norm(b, pk):
        k = (b, pk)
        if k not in norm_cache:
            if b not in ctxs:
                ctxs[b] = RunContext(load_book(b), st, cache, log=lambda *_: None)
            try:
                img = ctxs[b].image("char_patch", pk)
                norm_cache[k] = normalize_patch(to_canonical(binarize_page(img, edge_margin=0)))
            except Exception:
                norm_cache[k] = None
        return norm_cache[k]

    with open(out, "w", encoding="utf-8") as fh:
        for iid, label, norm in rows:
            b, pg, col, idx = iid.removeprefix("v1:").split(":")   # 重键后留下的 v1 带 v1: 前缀
            if not (lo <= int(pg) <= hi) or not idx.isdigit():
                continue
            mine = _unpng(norm)
            cands = []
            pcs = page_cells(b, int(pg))
            for cc, sl, sub, pk in pcs:
                if abs(cc - int(col)) > 1 or not (int(idx) - 3 <= sl <= int(idx) + 5):
                    continue
                cn = cur_norm(b, pk)
                if cn is None:
                    continue
                cands.append((float(verify_pair_elastic(mine, cn).f1), f"{b}:{int(pg)}:{cc}:{sl}{sub}"))
            cands.sort(key=lambda t: -t[0])
            if not cands:
                st_, cell, cov = ("nocells" if not pcs else "none"), None, 0.0
            else:
                cov, cell = cands[0]
                second = cands[1][0] if len(cands) > 1 else 0.0
                st_ = ("exact" if cov >= EXACT else
                       "match" if cov >= TH and cov - second >= MARGIN else "weak")
            fh.write(json.dumps({"v1": iid, "label": label, "cell": cell, "cov": round(cov, 4),
                                 "status": st_, "guess": f"{b}:{int(pg)}:{col}:{int(idx) + 1}"},
                                ensure_ascii=False) + "\n")
            n += 1
            if len(norm_cache) > 30000:
                norm_cache.clear()
    print("v1 刻例", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
