"""文字带窗口够不够装下一整列（char-segmentation/text-band）。

列的纵向窗口来自 phase2 的 `inner_frame` 上下界。版面检测把**正文中间的
某条横线**当成上框或下框时，窗口能塌到只剩三分之一页——窗外的字全部被
判空、静默丢掉。实测两册 21 张正文页中招，最惨的 vol02/97 只切出 47 个
字格（正文页中位 168）。

这个量**不需要人工标注**：文字带高是书级刚性常量

    应有窗口高 = 每列字数 × 书级格高（全书格高中位）

窗口短过它一大截就是版面检测认错了线。金标记「当前哪些页的窗口偏短、
偏到多少」，回归看的是：不许出现新的塌陷页，已塌的不许塌得更狠，
字格总数不许掉。

用法：PYTHONPATH=. python scripts/eval_text_band.py <数据集目录> [--update] [--source v2|v1]

## 2026-09-30（M1·A 道）：默认改读现行 v2 链

`--source v1`（旧）读 `./output/<册>/phase3_char_grid` + `phase2_layout`（退役链；云端没有，
旧脚本静默扫到 0 页，还会报「回归门失败：字格 47431→0」这种**假回归**）。
`--source v2`（默认）读 `products/<册>/`：

| 量 | v1 来源 | v2 来源 |
|---|---|---|
| 窗口高 | phase2 `inner_frame` 上下界 intercept 之差 | `border_detect` 的 `borders.top/bottom`（内框，页中线 x 处 `y_at`）之差 |
| 书级格高 | 全书 `grid.cell_h` 中位 | 全书 `row_segment` 的 `cells.period`（页级格高）中位 |
| 每列字数 | `chars_per_line` | 册定义 `books/<册>.yaml` 的 `chars_per_line`（21）|
| 字格数 | grid 里 `type==char` 的格 | `row_segment` 里 `kind=="char"` 的格（夹注 a/b、空白不计）|
| 「被放开/已核过」豁免 | `band_widened` / `band_checked` | **无对应物**（v2 窗口直接来自 Step1 边框，没有 Pass 2a4）；不豁免 |

判据不变：`比值 = 窗口高/(每列字数×书级格高) < 0.90` 记一张「窗口偏短」页；回归三条不变。
**金标是算法快照不是人裁**：v2 基线写 `text-band/expected_v2.json`（`--update` 冻结），
v1 的 `expected.json`（294 页 / 47431 格 / 偏短 vol01/50、vol01/88）留档，指的是退役链。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SHORT_T = 0.90      # 窗口高 / 应有 低于此 → 记一张「窗口偏短」页
DROP_TOL = 0.02     # 字格总数允许的下滑（比例）


def scan(dataset: str, out: str = "output") -> dict:
    gold = json.loads((Path(dataset).parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    body = {(r["book"], r["page"]) for r in gold if r["page_type"] == "body"}
    short: dict[str, float] = {}
    n_cells = 0
    n_pages = 0
    for book_dir in sorted(Path(out).glob("vol*")):
        book = book_dir.name
        grids = sorted((book_dir / "phase3_char_grid").glob("*_char_grid.json"))
        hs = []
        for gp in grids:
            ch = (json.loads(gp.read_text(encoding="utf-8")).get("grid")
                  or {}).get("cell_h")
            if ch:
                hs.append(ch)
        if not hs:
            continue
        cell_h = float(np.median(hs))
        for gp in grids:
            page = gp.stem.replace("_char_grid", "")
            if (book, page) not in body:
                continue
            g = json.loads(gp.read_text(encoding="utf-8"))
            n = g.get("chars_per_line") or 21
            lp = book_dir / "phase2_layout" / f"{page}_layout.json"
            if not lp.exists():
                continue
            n_pages += 1
            n_cells += sum(1 for c in g.get("columns") or []
                           for x in c.get("cells", []) if x.get("type") == "char")
            inner = (json.loads(lp.read_text(encoding="utf-8")).get("borders")
                     or {}).get("inner_frame") or {}
            t = (inner.get("top") or {}).get("intercept")
            b = (inner.get("bottom") or {}).get("intercept")
            band = g.get("grid", {}).get("band_widened")
            if band:
                continue          # 已被 Pass 2a4 放开，不再算塌陷
            if g.get("grid", {}).get("band_checked"):
                # Pass 2a4 拿真像素比过了：整页放开并**没有**更好
                # （漏墨没减半、字格没多、丢字没少）——短窗口在这一页
                # 没有造成覆盖损失。窗口比照旧偏短（上游 inner_frame
                # 的病，归 phase2 修），但不记成切分层的「塌陷」。
                # 2026-08-26：clip_refit 把这些页的原网格修准之后，
                # 11 张页从「靠放开窗口救回来」变成「本来就不用救」，
                # 字格 1800 → 1801、文字跨度逐页几乎不变。
                continue
            if t is None or b is None:
                continue
            ratio = (b - t) / (n * cell_h)
            if ratio < SHORT_T:
                short[f"{book}/{page}"] = round(ratio, 3)
    return {"short_threshold": SHORT_T, "n_body_pages": n_pages,
            "n_char_cells": n_cells, "short_pages": short}


def scan_v2(dataset: str) -> dict:
    import open_guji_cv.products.kinds  # noqa: F401  注册产物种类
    from open_guji_cv.core.book import load_book
    from open_guji_cv.products.store import ProductStore
    st = ProductStore()
    gold = json.loads((Path(dataset).parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    body = {(r["book"], int(r["page"])) for r in gold if r["page_type"] == "body"}
    short: dict[str, float] = {}
    n_cells = n_pages = 0
    ratios: list[float] = []
    per_book: dict[str, dict] = {}
    pages_info: dict[str, dict] = {}     # 每页 {ratio, cells}：回归只在基线与现扫的页交集上比
    for book_dir in sorted(Path(st.root).glob("vol*")):
        book = book_dir.name
        keys = [k for k in st.keys(book, "row_segment") if st.exists(book, "border_detect", k)]
        pcs = {}
        for k in keys:
            pc = st.read(book, "row_segment", k, "cells")
            if pc is not None and pc.period:
                pcs[k] = pc
        if not pcs:
            continue
        cell_h = float(np.median([pc.period for pc in pcs.values()]))
        n = load_book(book).chars_per_line or 21
        nb = 0
        for k, pc in sorted(pcs.items()):
            page = int(k[1:])
            if (book, page) not in body:
                continue
            b = st.read(book, "border_detect", k, "borders")
            if b is None:
                continue
            n_pages += 1
            nb += 1
            pg_cells = sum(1 for c in pc.columns for x in c.cells if x.kind == "char")
            n_cells += pg_cells
            xc = b.width / 2
            win = b.bottom.to_hline().y_at(xc) - b.top.to_hline().y_at(xc)
            ratio = win / (n * cell_h)
            ratios.append(ratio)
            pages_info[f"{book}/{page}"] = {"ratio": round(ratio, 3), "cells": pg_cells}
            if ratio < SHORT_T:
                short[f"{book}/{page}"] = round(ratio, 3)
        per_book[book] = {"pages": nb, "cell_h_median": round(cell_h, 2)}
    return {"short_threshold": SHORT_T, "source": "v2:borders+row_segment",
            "n_body_pages": n_pages, "n_char_cells": n_cells, "short_pages": short,
            "ratio_min": round(min(ratios), 3) if ratios else None,
            "ratio_median": round(float(np.median(ratios)), 3) if ratios else None,
            "per_book": per_book, "pages": pages_info}


def regress_v2(gold: dict, got: dict) -> None:
    """v2 回归：只在基线与本次扫描的**页交集**上比（云端没有全书产物时只扫到几页，
    拿 294 页的总格数去比就是假回归）；覆盖不全会明说。"""
    gpg, tpg = gold.get("pages", {}), got.get("pages", {})
    common = sorted(set(gpg) & set(tpg))
    print(f"[v2 链] 基线 {gold['n_body_pages']} 页 / {gold['n_char_cells']} 格；本次扫到 {got['n_body_pages']} 页，"
          f"与基线的页交集 {len(common)} 页"
          + ("" if len(common) == gold["n_body_pages"] else "（覆盖不全，只比交集）"))
    gp = {k: v["ratio"] for k, v in gpg.items() if v["ratio"] < SHORT_T and k in tpg}
    tp = {k: tpg[k]["ratio"] for k in common if tpg[k]["ratio"] < SHORT_T}
    print(f"窗口偏短页（交集内）{len(gp)} → {len(tp)}")
    new = sorted(set(tp) - set(gp))
    gone = sorted(set(gp) - set(tp))
    worse = [k for k in sorted(set(tp) & set(gp)) if tp[k] < gp[k] - 0.01]
    for k in gone:
        print(f"  ✔ 修好 {k}（基线 {gp[k]}）")
    for k in new:
        print(f"  ✗ 新塌陷 {k} {tp[k]}")
    for k in worse:
        print(f"  ✗ 塌得更狠 {k} {gp[k]} → {tp[k]}")
    gc = sum(gpg[k]["cells"] for k in common)
    tc = sum(tpg[k]["cells"] for k in common)
    print(f"交集内字格 {gc} → {tc}")
    lost = tc < gc * (1 - DROP_TOL)
    if lost:
        print(f"  ✗ 字格总数掉了超过 {DROP_TOL:.0%}")
    ok = not new and not worse and not lost
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--source", choices=("v2", "v1"), default="v2")
    ap.add_argument("--update", action="store_true",
                    help="把当前实测写回金标（只在确认是改进时用）")
    a = ap.parse_args()
    v2 = a.source == "v2"
    shard = Path(a.dataset) / "text-band" / ("expected_v2.json" if v2 else "expected.json")
    got = scan_v2(a.dataset) if v2 else scan(a.dataset, a.out)
    if v2 and got["n_body_pages"] == 0:
        raise SystemExit("v2 产物里没有可用的正文页（需要 border_detect + row_segment）——"
                         "先跑 guji pipeline / eval --from-raw；不是「0 页 0 格」")
    if v2 and not a.update and not shard.exists():
        print(f"v2 实测：正文 {got['n_body_pages']} 页、字格 {got['n_char_cells']}、"
              f"窗口偏短 {len(got['short_pages'])} 页 {got['short_pages']}；"
              f"比值 最小 {got['ratio_min']} / 中位 {got['ratio_median']}；{got['per_book']}")
        v1 = Path(a.dataset) / "text-band" / "expected.json"
        if v1.exists():
            g1 = json.loads(v1.read_text(encoding="utf-8"))
            print(f"（对照 v1 旧基线：{g1['n_body_pages']} 页 / {g1['n_char_cells']} 格 / "
                  f"偏短 {g1['short_pages']}）")
        print("还没有 v2 基线（expected_v2.json）——不做回归判定；确认后用 --update 冻结")
        return
    if a.update or (not v2 and not shard.exists()):
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"写入金标：正文 {got['n_body_pages']} 页、字格 "
              f"{got['n_char_cells']}、窗口偏短 {len(got['short_pages'])} 页 → {shard}")
        return
    gold = json.loads(shard.read_text(encoding="utf-8"))
    if v2:
        return regress_v2(gold, got)
    gp, tp = gold.get("short_pages", {}), got.get("short_pages", {})
    print(f"正文页 {gold['n_body_pages']} → {got['n_body_pages']}；"
          f"字格 {gold['n_char_cells']} → {got['n_char_cells']}")
    print(f"窗口偏短页 {len(gp)} → {len(tp)}")
    new = sorted(set(tp) - set(gp))
    gone = sorted(set(gp) - set(tp))
    worse = [k for k in sorted(set(tp) & set(gp)) if tp[k] < gp[k] - 0.01]
    for k in gone:
        print(f"  ✔ 修好 {k}（金标 {gp[k]}）")
    for k in new:
        print(f"  ✗ 新塌陷 {k} {tp[k]}")
    for k in worse:
        print(f"  ✗ 塌得更狠 {k} {gp[k]} → {tp[k]}")
    lost = got["n_char_cells"] < gold["n_char_cells"] * (1 - DROP_TOL)
    if lost:
        print(f"  ✗ 字格总数掉了超过 {DROP_TOL:.0%}")
    ok = not new and not worse and not lost
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
