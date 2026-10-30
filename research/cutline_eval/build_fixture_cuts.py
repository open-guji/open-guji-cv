"""把 A 批切线金标(196 active)+ 矮格 3 格冻结成 Step3 回归 fixture:tests/fixtures/cutline/。
存:每个涉及的列的 `column_image`(Step3 的输入,1-bit PNG)+ manifest(segment_column 的页/列参数、
冻结的现役 boundaries〔U-Net 裁判〕、冻结的 rule-only boundaries〔cut_judge=None,无 torch 也能复现〕、金标)。
用法(需 GUJI_WORKSPACE/GUJI_PRODUCTS_DIR 指向含 vol02 原图+snap 产物的工作区):
  python3 -I build_fixture_cuts.py <A批 items.jsonl> <out_dir>"""
import sys, json, pathlib, collections, numpy as np, cv2
from PIL import Image
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu.row_boundaries import segment_column
RUNT = [(15, 9, 20), (113, 1, 4), (188, 4, 20)]
def main(items, out):
    out = pathlib.Path(out); (out / "cols").mkdir(parents=True, exist_ok=True)
    book = load_book("vol02"); ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None)
    p = ctx.params_for(ctx.producer("cells"))
    gold = []
    for l in open(items, encoding="utf-8"):
        d = json.loads(l)
        if d.get("input", {}).get("source") != "L3-batch" or d["anchor"]["book"] != "vol02": continue
        e = d["expected"]
        if d.get("status") == "uncertain" or e.get("y") is None: continue
        gold.append(dict(id=d["id"], page=d["anchor"]["page"], col=d["anchor"]["col"], slot_above=e["slot_above"], y_gold=e["y"], verdict=e["verdict"],
                         stratum=d.get("stratum"), w=d.get("stratum_weight"), col_h=e.get("col_h")))
    keys = sorted({(g["page"], g["col"]) for g in gold} | {(a, b) for a, b, _ in RUNT})
    cols = {}
    for pg, col in keys:
        rs = ctx.store.read("vol02", "row_segment", page_key(pg), "cells"); cc = next(c for c in rs.columns if c.col == col)
        img = cv2.imdecode(np.fromfile(str(ctx.materialize("column_image", column_key(pg, col))), np.uint8), cv2.IMREAD_GRAYSCALE)
        b = np.where(img < 128, 0, 255).astype(np.uint8)
        Image.fromarray(b >= 128).convert("1").save(out / "cols" / f"p{pg}_c{col}.png", optimize=True)
        kw = dict(period=float(rs.period), n_body_slots=int(cc.n_body_slots), n_raised=int(cc.n_raised), border_top=float(cc.border_top),
                  border_bottom=None if cc.border_bottom is None else float(cc.border_bottom), ref_w=None if rs.ref_w is None else float(rs.ref_w),
                  top_slack=float(cc.top_slack), content_x=None if cc.content_x is None else tuple(float(x) for x in cc.content_x))
        run_kw = dict(ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio, raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu,
                      seam_band=p.seam_band, detect_bottom_bar=p.detect_bottom_bar)
        r = segment_column(b, cut_judge=None, **kw, **run_kw)
        cols[f"p{pg}_c{col}"] = dict(page=pg, col=col, file=f"cols/p{pg}_c{col}.png", segment_kwargs=kw, run_kwargs=run_kw,
                                     frozen_boundaries=[round(float(x), 1) for x in cc.boundaries],
                                     frozen_rule_boundaries=None if r is None else [round(float(x), 1) for x in r.boundaries])
    # 冻结的现役(U-Net)切点 vs 金标
    for g in gold:
        c = cols[f"p{g['page']}_c{g['col']}"]; nr = c["segment_kwargs"]["n_raised"]
        # 抬头列(n_raised>0):物理位置 pos = slot + n_raised(负 slot 为抬头格),boundaries 按 pos 排
        g["y_frozen"] = c["frozen_boundaries"][g["slot_above"] + nr if g["slot_above"] > 0 else g["slot_above"] + nr]
    ag = sum(1 for g in gold if abs(g["y_gold"] - g["y_frozen"]) <= 3)
    nrule = sum(1 for c in cols.values() if c["frozen_rule_boundaries"] is not None)
    same_rule = sum(1 for c in cols.values() if c["frozen_rule_boundaries"] is not None and len(c["frozen_rule_boundaries"]) == len(c["frozen_boundaries"]) and max(abs(a - b) for a, b in zip(c["frozen_rule_boundaries"], c["frozen_boundaries"])) <= 1.0)
    print(f"金标 {len(gold)} 条,唯一列 {len(cols)};现役切点与金标 ≤3px 一致 {ag}/{len(gold)};rule-only 可算 {nrule}/{len(cols)} 列,其中与现役(U-Net)边界逐点≤1px 一致 {same_rule}")
    json.dump(dict(book="vol02", source="dataset claude/A-cutline-vol02-1011-harvest 5de7ff2 touching-cuts L3-batch", runt_cells=RUNT, columns=cols, gold=gold),
              open(out / "manifest.json", "w"), ensure_ascii=False, indent=0)
if __name__ == "__main__": main(sys.argv[1], sys.argv[2])
