"""字身墨分片：2b 字带左右边（`column_band`）与 2e 字框压缩（`cell_shrink`）的「字身墨被抹／被切」护栏（CV2，2026-11-28，四大步验收 L4）。

金标怎么来（不靠人画框，靠人核过的格界＋墨的连通域）：
cut-bench（`char-segmentation/cut-bench/<书>/`）里人核过的列（label_origin human／checked），取**列中**的字格（去掉每列首、尾格，
那归 cut-frame），在原图上取格四边形外包往外扩 0.3 格的范围做二值连通域；**干净格**＝没有一个连通域横跨格界
（跨格界的笔画粘连、贴着界行的格都不收），字身墨框＝格内全部连通域的外包。干净格的格界只要落在字缝里任何地方，
墨框都一样，所以 checked 列只核到字数（`checked_level: count`）也能用。

    # 建分片（要冻结好的 cut-bench：原图＋金标）
    python -m open_guji_cv.eval.cut_ink build --bench <bench 根> --books shiji,qtw --out <dataset>/char-segmentation \
        [--per-book 150] [--band-cols 30] [--seed 1128]
    # 2e：紧框不切字身墨（同 cut-frame 的打分）
    python -m open_guji_cv.eval.cut_frame --items <dataset>/char-segmentation/shrink-ink/items.jsonl --pred <产物根>
    # 2b：字带不抹字身墨
    python -m open_guji_cv.eval.cut_ink band --items <dataset>/char-segmentation/band-ink/items.jsonl --pred <产物根> \
        [--against <另一产物根>] [--tol 2] [--json out.json]

2b 打分：读 `<册>/column_warp/pNNNN.json`（`column_windows`）与 `<册>/column_band/pNNNN.json`（`column_bands`），
把字带左右边按列窗口映回原图（`steps/_warpmap.ColumnMapper`），在每个干净格的纵向范围里取字带最窄处，
字身墨框伸出字带超过 `tol` 像素记**抹墨**（护栏，必须为 0／不增）；另报字带到字身墨的余量（中位、p10，像素）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

#: 格外包往外扩多少格高／格宽取连通域
PAD = 0.3
#: 小于这个面积（像素）的连通域当噪点（纸面墨点），不进字身墨框、也不算跨界。
#: 刻本字的点画在 cut-bench 原图上一般 ≥100 像素；6 像素时全唐文 9 格的墨框被格边墨点撑大（11-28 看图）
MIN_AREA = 30
#: 二值门槛（灰度 < INK 算墨），与 cut_bench 细档一致
INK = 128
#: 2e 每列至多抽几格
PER_COL = 3


def _box(q):
    xs = [p[0] for p in q]
    ys = [p[1] for p in q]
    return min(xs), min(ys), max(xs), max(ys)


def _split(key: str) -> str:
    """盲测：键 sha1 整数除 3 余 0（同 cut-lattice、cut-frame 口径）。"""
    return "blind" if int(hashlib.sha1(key.encode()).hexdigest(), 16) % 3 == 0 else "tune"


def clean_ink_box(ink, W: int, quad) -> tuple[list[float] | None, str]:
    """一格的字身墨框（原图坐标 raw_page_px@top-right，[x0,y0,x1,y1]）。不干净返回 (None, 原因)。
    `ink`：整页二值（True＝墨，图像坐标左上原点）。"""
    import cv2
    import numpy as np
    x0, y0, x1, y1 = _box(quad)                       # 页坐标（x 从右量）
    X0, X1 = W - x1, W - x0                           # 图像坐标
    w, h = X1 - X0, y1 - y0
    H = ink.shape[0]
    a0, a1 = max(0, int(X0 - PAD * w)), min(W, int(X1 + PAD * w) + 1)
    b0, b1 = max(0, int(y0 - PAD * h)), min(H, int(y1 + PAD * h) + 1)
    sub = ink[b0:b1, a0:a1].astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(sub, connectivity=8)
    cx0, cx1, cy0, cy1 = X0 - a0, X1 - a0, y0 - b0, y1 - b0
    boxes = []
    for i in range(1, n):
        bx, by, bw, bh, area = st[i]
        if area < MIN_AREA:
            continue
        ex0, ey0, ex1, ey1 = bx, by, bx + bw, by + bh
        if ex1 <= cx0 or ex0 >= cx1 or ey1 <= cy0 or ey0 >= cy1:
            continue                                   # 整个在格外
        if ex0 < cx0 - 0.5 or ex1 > cx1 + 0.5 or ey0 < cy0 - 0.5 or ey1 > cy1 + 0.5:
            return None, "跨格界"
        boxes.append((ex0, ey0, ex1, ey1, area))
    if not boxes or sum(b[4] for b in boxes) < 40:
        return None, "墨太少"
    gx0 = min(b[0] for b in boxes) + a0
    gx1 = max(b[2] for b in boxes) + a0
    gy0 = min(b[1] for b in boxes) + b0
    gy1 = max(b[3] for b in boxes) + b0
    return [round(float(W - gx1), 1), round(float(gy0), 1), round(float(W - gx0), 1), round(float(gy1), 1)], "ok"


def _raw_page(bench: Path, vol: str, page: int):
    import cv2

    from ..utils.image_io import imread as cv_imread
    from .cut_bench import _raw_dir
    im = cv_imread(str(_raw_dir(bench, vol) / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    return None if im is None else (im < INK)


def build(a) -> None:
    from .cut_bench import iter_gold
    out_root = Path(a.out)
    rng = random.Random(a.seed)
    shrink, band, stats = [], [], {}
    for book in a.books.split(","):
        bench = Path(a.bench) / book
        cand = []                                     # (列键, 格行)
        why = defaultdict(int)
        page_ink = {}
        for vol, page, g in iter_gold(bench, only=("human", "checked")):
            body = [c for c in g["cells"] if c.get("kind") in ("char", "jiazhu", "jiazhu_solo")]
            if len(body) < 3:
                continue
            if (vol, page) not in page_ink:
                page_ink[(vol, page)] = _raw_page(bench, vol, page)
            ink = page_ink[(vol, page)]
            if ink is None:
                continue
            W = ink.shape[1]
            slots = [c["slot"] for c in body]
            lo, hi = min(slots), max(slots)
            for c in body:
                if c["slot"] in (lo, hi):            # 列首、列尾格归 cut-frame（2c）
                    why["列端"] += 1
                    continue
                box, w = clean_ink_box(ink, W, c["quad"])
                why[w] += 1
                if box is None:
                    continue
                key = f"{book}:{vol}:{page}:{g['col']}:{c['slot']}" + (f":{c['sub']}" if c.get("sub") else "")
                cand.append((f"{book}:{vol}:{page}:{g['col']}", {
                    "key": key, "book": book, "vol": str(vol), "page": page, "col": g["col"], "slot": c["slot"],
                    "sub": c.get("sub"), "kind": c["kind"], "split": _split(key), "status": "ok",
                    "tight": box, "quad": [[round(x, 1), round(y, 1)] for x, y in c["quad"]],
                    "label_origin": f"derived:{g['label_origin']}", "tags": [], "coord": "raw_page_px@top-right"}))
        by_col = defaultdict(list)
        for k, r in cand:
            by_col[k].append(r)
        cols = sorted(by_col)
        rng.shuffle(cols)
        # 2e：按列轮抽，每列至多 PER_COL 格，凑够 per_book 格（不让一两列独占）
        n = 0
        for k in cols:
            if n >= a.per_book:
                break
            rows = by_col[k][:]
            rng.shuffle(rows)
            take = sorted(rows[:PER_COL], key=lambda r: (r["slot"], r["sub"] or ""))
            shrink += take
            n += len(take)
        # 2b：抽 band_cols 列，一列的干净格全收
        for k in sorted(cols[:a.band_cols]):
            rows = by_col[k]
            r0 = rows[0]
            band.append({"key": k, "book": book, "vol": r0["vol"], "page": r0["page"], "col": r0["col"],
                         "split": _split(k), "status": "ok",
                         "cells": [{"slot": r["slot"], "sub": r["sub"], "ink": r["tight"]} for r in rows],
                         "label_origin": "derived:cut-bench", "coord": "raw_page_px@top-right"})
        pk = set(cols[:a.band_cols])
        stats[book] = {"cand_cells": len(cand), "cand_cols": len(cols), "shrink_cells": n, "band_cols": len(pk), "why": dict(why)}
    for name, rows in (("shrink-ink", shrink), ("band-ink", band)):
        d = out_root / name
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "items.jsonl", "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cnt = {"stats": stats,
           "shrink_ink": {f"{b}:{s}": sum(1 for r in shrink if r["book"] == b and r["split"] == s)
                          for b in a.books.split(",") for s in ("tune", "blind")},
           "band_ink_cols": {f"{b}:{s}": sum(1 for r in band if r["book"] == b and r["split"] == s)
                             for b in a.books.split(",") for s in ("tune", "blind")}}
    (out_root / "shrink-ink" / "counts.json").write_text(json.dumps(cnt, ensure_ascii=False, indent=1))
    print(json.dumps(cnt, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 2b 打分
def _band_edges(root: Path, vol: str, page: int) -> dict | None:
    """{列号: [(page_y, x_tr 左右两边的 (lo, hi))…]}：字带左右边映回原图，每 8 列图像素一点。"""
    from ..products.kinds.columns import PageBands, PageWindows
    from ..steps._warpmap import ColumnMapper
    fw = root / vol / "column_warp" / f"p{page:04d}.json"
    fb = root / vol / "column_band" / f"p{page:04d}.json"
    if not (fw.exists() and fb.exists()):
        return None
    win = PageWindows.model_validate(json.loads(fw.read_text())["column_windows"])
    bands = PageBands.model_validate(json.loads(fb.read_text())["column_bands"])
    W = win.page_size[0]
    out = {}
    for b in bands.columns:
        wrec = win.column(b.col)
        if wrec is None:
            continue
        m = ColumnMapper.of(W, wrec)
        pts = []
        for y in range(0, int(m.out_h), 8):
            xa, ya = m.to_page_tr(float(b.band[0]), float(y))
            xb, yb = m.to_page_tr(float(b.band[1]), float(y))
            pts.append(((ya + yb) / 2, min(xa, xb), max(xa, xb)))
        out[b.col] = pts
    return out


def band_score(items: list[dict], root: Path, tol: float = 2.0) -> dict:
    agg = defaultdict(lambda: {"cols": 0, "cells": 0, "erase": 0, "erase_cols": 0, "missing": 0, "margins": []})
    cells, cache = {}, {}
    for r in items:
        pk = (r["vol"], r["page"])
        if pk not in cache:
            cache[pk] = _band_edges(root, r["vol"], r["page"])
        e = (cache[pk] or {}).get(r["col"])
        col_erase = False
        for c in r["cells"]:
            ck = f"{r['key']}:{c['slot']}" + (f":{c['sub']}" if c.get("sub") else "")
            gx0, gy0, gx1, gy1 = c["ink"]
            pts = [p for p in (e or []) if gy0 <= p[0] <= gy1]
            if not pts:
                j = {"missing": True, "erase": False, "margin": None}
            else:
                lo, hi = max(p[1] for p in pts), min(p[2] for p in pts)   # 这一格纵向范围里字带最窄处
                out_l, out_r = lo - gx0, gx1 - hi                         # >0：字身墨伸出字带
                j = {"missing": False, "erase": max(out_l, out_r) > tol,
                     "margin": round(min(-out_l, -out_r), 1), "out": [round(out_l, 1), round(out_r, 1)]}
            cells[ck] = j
            col_erase |= j["erase"]
            for k in (r["book"], "all", f"split:{r.get('split', '-')}"):
                a = agg[k]
                a["cells"] += 1; a["erase"] += j["erase"]; a["missing"] += j["missing"]
                if j["margin"] is not None:
                    a["margins"].append(j["margin"])
        for k in (r["book"], "all", f"split:{r.get('split', '-')}"):
            agg[k]["cols"] += 1; agg[k]["erase_cols"] += col_erase
    groups = {}
    for k, v in agg.items():
        m = sorted(v.pop("margins"))
        v["margin_px"] = {"median": m[len(m) // 2] if m else None, "p10": m[len(m) // 10] if m else None}
        groups[k] = v
    return {"tol": tol, "groups": groups, "cells": cells}


def band(a) -> None:
    items = [json.loads(l) for l in Path(a.items).read_text(encoding="utf-8").splitlines() if l.strip()]
    root = Path(a.pred)
    vols = {p.name for p in root.iterdir() if (p / "column_band").is_dir()}
    items = [r for r in items if r["vol"] in vols and r.get("status", "ok") == "ok" and (not a.split or r["split"] == a.split)]

    def show(r, title):
        print(title)
        for k, v in sorted(r["groups"].items(), key=lambda kv: (kv[0] != "all", kv[0])):
            print(f"  {k:14s} 列 {v['cols']:3d} 格 {v['cells']:4d}  抹墨格 {v['erase']}（列 {v['erase_cols']}）  缺 {v['missing']}"
                  f"  余量 px 中位 {v['margin_px']['median']} p10 {v['margin_px']['p10']}")

    r = band_score(items, root, a.tol)
    show(r, f"2b 字带抹墨（{a.items}，容差 {a.tol}px）")
    out = {"pred": r}
    if a.against:
        b = band_score(items, Path(a.against), a.tol)
        show(b, f"对照 {a.against}")
        fl = [{"key": k, "a": b["cells"][k], "b": v} for k, v in r["cells"].items()
              if k in b["cells"] and b["cells"][k]["erase"] != v["erase"]]
        print(f"翻转 {len(fl)} 格（新抹墨 {sum(1 for f in fl if f['b']['erase'])}）")
        for f in fl:
            print(f"  {'坏' if f['b']['erase'] else '好'} {f['key']}: 伸出 {f['a'].get('out')} → {f['b'].get('out')}")
        out.update(against=b, flips=fl)
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--bench", required=True); b.add_argument("--books", default="shiji,qtw"); b.add_argument("--out", required=True)
    b.add_argument("--per-book", dest="per_book", type=int, default=150); b.add_argument("--seed", type=int, default=1128)
    b.add_argument("--band-cols", dest="band_cols", type=int, default=30, help="2b 每书抽几列")
    s = sub.add_parser("band")
    s.add_argument("--items", required=True); s.add_argument("--pred", required=True); s.add_argument("--against")
    s.add_argument("--split", choices=["tune", "blind"]); s.add_argument("--tol", type=float, default=2.0); s.add_argument("--json")
    a = ap.parse_args(argv)
    {"build": build, "band": band}[a.cmd](a)


if __name__ == "__main__":
    main()
