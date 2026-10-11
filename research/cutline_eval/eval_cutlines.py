"""切线金标 × 现行 Step3(row_segment)逐线对账。只评测,不改 steps/*。

用法(需 GUJI_PRODUCTS_DIR 指向含 column_warp+row_segment 产物的目录,如 vol02 snap):
  python3 -I eval_cutlines.py <items.jsonl> [--source L3-batch|old|all] [--book vol02] [--out report.json]
对每条金标 (book,page,col,slot_above):
  y_gold = expected.y(列图行坐标);col_h = expected.col_h(金标时列图高度);
  y_eng  = 现役 row_segment 该列 boundaries[slot_above](= slot_above 格的 y1);
  坐标核对:现役 column_warp 的 warped_size[1] 与 col_h 差 >2px 记 'coord_stale',不比较(需 remap)。
分类(互斥,按序):
  idk/uncertain → 'uncertain'(不进指标);tags 非空(stain/border/residue/other)→ 'tagged';verdict=overlap → 'overlap'(切哪都伤);
  无产物/无该线 → 'no_engine_line';|dy|<=T_OK → 'ok';其余按 dy 符号与大小分档:'late_small'(3<dy<=8)…。
分层超采样:有 stratum_weight 的按权加权给估计,**不报全书率**,报告两份(等权/加权)。"""
import sys, json, argparse, collections, os, statistics as st
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
T_OK = 3.0
def bin_dy(dy):
    a = abs(dy)
    tag = "gold_below_engine(引擎切早/偏上)" if dy > 0 else "gold_above_engine(引擎切晚/偏下)"
    if a <= T_OK: return "ok"
    if a <= 8: return "small_" + ("down" if dy > 0 else "up")
    if a <= 25: return "mid_" + ("down" if dy > 0 else "up")
    return "large_" + ("down" if dy > 0 else "up")
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("items"); ap.add_argument("--source", default="L3-batch"); ap.add_argument("--book", default="vol02"); ap.add_argument("--out")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.items, encoding="utf-8") if l.strip()]
    sel = []
    for d in rows:
        if d["anchor"]["book"] != a.book: continue
        src = d.get("input", {}).get("source", "old")
        if a.source != "all" and src != a.source: continue
        sel.append(d)
    ctx = RunContext(load_book(a.book), ProductStore(), ImageCache(), log=lambda s: None)
    cache = {}
    def page(pg):
        if pg not in cache:
            try:
                rs = ctx.store.read(a.book, "row_segment", page_key(pg), "cells")
                cw = ctx.store.read(a.book, "column_warp", page_key(pg), "column_windows")
            except Exception:                                     # noqa: BLE001
                rs = cw = None
            cache[pg] = (rs, cw)
        return cache[pg]
    out = []
    for d in sel:
        an, e = d["anchor"], d["expected"]; pg, col, slot = an["page"], an["col"], e.get("slot_above") or an.get("slot")
        w = float(d.get("stratum_weight") or d.get("input", {}).get("stratum_weight") or 1.0)
        rec = dict(id=d["id"], verdict=e.get("verdict"), tags=e.get("tags") or [], w=w, y_gold=e.get("y"), y_old=e.get("y_old"))
        rs, cw = page(pg)
        if e.get("verdict") in ("idk", "uncertain") or d.get("status") == "uncertain" or e.get("y") is None: rec["cls"] = "uncertain"
        elif e.get("tags"): rec["cls"] = "tagged"
        elif e.get("verdict") == "overlap": rec["cls"] = "overlap"
        elif rs is None: rec["cls"] = "no_engine_line"
        else:
            cc = next((c for c in rs.columns if getattr(c, "col", None) == col), None)
            if cc is None or not getattr(cc, "boundaries", None) or slot is None or slot >= len(cc.boundaries): rec["cls"] = "no_engine_line"
            else:
                wc = next((x for x in cw.columns if x.col == col), None)
                H = wc.warped_size[1] if wc is not None else None
                if e.get("col_h") and H and abs(H - e["col_h"]) > 2: rec["cls"] = "coord_stale"; rec["H_now"] = H; rec["col_h"] = e["col_h"]
                else:
                    y_eng = float(cc.boundaries[slot]); rec["y_eng"] = y_eng; dy = float(e["y"]) - y_eng; rec["dy"] = round(dy, 1); rec["cls"] = bin_dy(dy)
        out.append(rec)
    c = collections.Counter(r["cls"] for r in out); cw_ = collections.defaultdict(float)
    for r in out: cw_[r["cls"]] += r["w"]
    print(f"n={len(out)} (book={a.book} source={a.source})")
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]): print(f"  {k:16s} {v:4d}  加权 {cw_[k]:8.1f}")
    dys = [abs(r["dy"]) for r in out if "dy" in r]
    if dys: print(f"  可比 {len(dys)} 条:|dy| 中位 {st.median(dys):.1f}px,p90 {sorted(dys)[int(len(dys)*.9)]:.1f}px,>3px 占 {sum(x>T_OK for x in dys)/len(dys):.0%}")
    if a.out: json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=0)
if __name__ == "__main__": main()
