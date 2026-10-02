# -*- coding: utf-8 -*-
"""S1 道：把测试集页的「带内全部下版框候选 + 信号」展开成一张表（pickle）。

三类页：
- gold   : `border-detection/bottom-offset/frozen_absolute.jsonl` 187 页（全是人挪过线的难页）；
- inner14: `border-detection/samples/*.json` 14 页（只有内框线 `bottom_inner`，口径不同——只当负担保）；
- body   : 等距抽样的正文页（page-type 金标 body），不在 gold/inner14 里的，当负担保。

只跑 `find_horizontal_border`（同 `scripts/eval_bottom_offset_oneside.py` 口径，不含 push_bottom_to_bar），
用「记录型 chooser」记下候选后原样返回现役线，所以 `rule_final` 就是现役输出。

    GUJI_WORKSPACE=<沙箱> GUJI_PRODUCTS_DIR=<沙箱>/products \\
        python scripts/experiments/bottom_peak/build_table.py --out table.pkl [--jobs 4]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
DATASET = ROOT.parent / "open-guji-dataset"
INK = 128


def pages_list(n_body_per_book: int):
    gold = [json.loads(l) for l in (DATASET / "border-detection/bottom-offset/frozen_absolute.jsonl").read_text("utf-8").splitlines() if l.strip()]
    out = [dict(kind="gold", book=g["book"], page=g["page"], y_left_abs=g["y_left_abs"], y_right_abs=g["y_right_abs"]) for g in gold]
    seen = {(g["book"], g["page"]) for g in gold}
    for f in sorted((DATASET / "border-detection/samples").glob("*.json")):
        d = json.loads(f.read_text("utf-8"))
        bi = d["bottom_inner"]
        # 新坐标 y_at_right = x=0（页右端）处的 y，右上原点；旧坐标 y 方向同向，只有 x 翻转
        out.append(dict(kind="inner14", book=d["book"], page=int(d["page"]),
                        inner_y_right=bi["y_at_right"], inner_slope=bi["slope"], w=d["width"]))
        seen.add((d["book"], int(d["page"])))
    body = {}
    for l in (DATASET / "page-type/items.jsonl").read_text("utf-8").splitlines():
        r = json.loads(l)
        if r["expected"]["page_type"] == "body":
            body.setdefault(r["anchor"]["book"], []).append(r["anchor"]["page"])
    for book in ("vol01", "vol02", "vol03"):
        ps = sorted(p for p in body.get(book, []) if (book, p) not in seen)
        if not ps:
            continue
        step = max(1, len(ps) // n_body_per_book)
        for p in ps[::step][:n_body_per_book]:
            out.append(dict(kind="body", book=book, page=p))
    return out


def run_page(it: dict):
    import cv2
    import numpy as np
    from open_guji_cv.bottompeak_model.signals import enumerate_candidates
    from open_guji_cv.core.book import load_book
    from open_guji_cv.utils.peak_line_search import find_horizontal_border, find_vertical_lines
    b = load_book(it["book"])
    gray = cv2.imread(str(b.raw_path(it["page"])), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    h, w = gray.shape
    mask = (gray < INK).astype(np.float64)
    vl = find_vertical_lines(mask, expected_count=b.expected_cols + 1)
    tkw = {} if b.top_band_frac is None else {"band_frac": float(b.top_band_frac)}
    top = find_horizontal_border(mask, "top", **tkw)
    rec = {}

    def spy(mask_, cur, verticals, book_gap, lo, hi):
        rec["cands"] = enumerate_candidates(mask_, cur, verticals, book_gap, lo, hi, top.position)
        rec["cur"] = cur
        return cur
    m = find_horizontal_border(mask, "bottom", verticals=vl, book_gap=b.bottom_gap, bottom_chooser=spy)
    cands = rec.get("cands", [])
    rows = [dict(final=c["final"], peak=c["line"].position, **c["feats"]) for c in cands]
    return dict(it, w=w, h=h, slope=m.slope, rule_final=m.position, top=top.position, rows=rows,
                bottom_gap=b.bottom_gap)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--n-body", type=int, default=24, help="每册等距抽样的正文页数")
    a = ap.parse_args()
    items = pages_list(a.n_body)
    print(f"{len(items)} 页", flush=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        res = [r for r in ex.map(run_page, items, chunksize=2) if r]
    Path(a.out).write_bytes(pickle.dumps(res))
    print(f"写 {len(res)} 页 → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
