# -*- coding: utf-8 -*-
"""把 bxgb 每个字位（Step4 char_index 的一条）导成一行 JSONL，汇总 Step3–Step7 的证据。

用法：
  python export_cells.py [--ws <工作区>] [--book bxgb] [--out cells_bxgb.jsonl]

只读 products/<book>/<step>/p*.json，不 import 引擎、不写工作区。
key = 字位 id（book:page:col:slot[a|b]，与各步产物的 id 同口径）。
阅读序号：
  col_order  = Step3 cells 的列内读序（CellRec.order）
  page_order = 页内读序（按 col 升序、再按 col_order；col 1 是最右列，竖排右起）
  seq        = 全书读序（按 page、page_order）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

DEFAULT_WS = "/home/user/guji-workspace/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一"


def load_step(root: Path, step: str, kind: str) -> dict[int, dict]:
    out = {}
    for f in sorted(glob.glob(str(root / step / "p*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        d = d.get(kind, d)
        out[int(d.get("page") or int(Path(f).stem[1:]))] = d
    return out


def by_id(page_prod: dict | None, list_key: str = "chars") -> dict[str, dict]:
    if not page_prod:
        return {}
    res = {}
    if "columns" in page_prod:
        for col in page_prod["columns"]:
            for r in col.get(list_key, []):
                res[r["id"]] = r
    else:  # align_ref：扁平 chars
        for r in page_prod.get(list_key, []):
            res[r["id"]] = r
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default=os.environ.get("GUJI_WORKSPACE", DEFAULT_WS))
    ap.add_argument("--book", default="bxgb")
    ap.add_argument("--out", default=str(Path(__file__).with_name("cells_bxgb.jsonl")))
    a = ap.parse_args()
    root = Path(a.ws) / "products" / a.book

    cells = load_step(root, "row_segment", "cells")
    chars = load_step(root, "cell_shrink", "char_index")
    gm = load_step(root, "glyph_match", "glyph_match")
    ocr = load_step(root, "ocr_candidates", "ocr_candidates")
    rare = load_step(root, "rare_candidates", "rare_candidates")
    aln = load_step(root, "align_ref", "align_ref")
    dec = load_step(root, "context_decide", "context_decision")
    adm = load_step(root, "seed_admit", "seed_admit")

    rows = []
    for page in sorted(chars):
        # Step3 格：(col, slot, sub) → CellRec
        cmap = {}
        for col in (cells.get(page) or {}).get("columns", []):
            for c in col.get("cells", []):
                cmap[(col["col"], c["slot"], c.get("sub"))] = c
        g, o, r = by_id(gm.get(page)), by_id(ocr.get(page)), by_id(rare.get(page))
        al, de, ad = by_id(aln.get(page)), by_id(dec.get(page)), by_id(adm.get(page))
        prow = []
        for col in chars[page]["columns"]:
            for ch in col.get("chars", []):
                cid = ch["id"]
                cell = cmap.get((col["col"], ch["slot"], ch.get("sub"))) or {}
                m, oc, ra = g.get(cid), o.get(cid), r.get(cid)
                al_, de_, ad_ = al.get(cid), de.get(cid), ad.get(cid)
                prow.append({
                    "key": cid, "page": page, "col": col["col"], "slot": ch["slot"],
                    "sub": ch.get("sub"), "pos": ch.get("pos"),
                    "kind": cell.get("kind"),               # Step3：char/blank/jiazhu_a/b/solo
                    "step3_kind": ch.get("step3_kind"),     # Step4 记的 Step3 判定
                    "cell_type": ch.get("cell_type"),       # Step4：char | empty
                    "raised": cell.get("raised", False),
                    "col_order": cell.get("order"),
                    "patch_key": ch.get("patch_key"),
                    "bbox_page": ch.get("bbox_page"),
                    "flags": ch.get("flags") or [],
                    "s5a": None if m is None else {
                        "verdict": m.get("verdict"), "char": m.get("char"), "cov": m.get("cov"),
                        "wmax": m.get("wmax"), "candidates": m.get("candidates"),
                        "matched_id": m.get("matched_id"), "guard": m.get("guard"),
                        "n_verified": m.get("n_verified"), "via": m.get("via")},
                    "s5c_ocr": None if oc is None else {"topk": oc.get("topk"), "engine": oc.get("engine")},
                    "s5b_rare": None if ra is None else ra.get("candidates"),
                    "s5d": None if al_ is None else {
                        "align_char": al_.get("align_char"), "align_op": al_.get("align_op"),
                        "ref_run": al_.get("ref_run")},
                    "s6": None if de_ is None else {
                        "char": de_.get("char"), "ranked": de_.get("ranked"), "margin": de_.get("margin"),
                        "source": de_.get("source"), "used_context": de_.get("used_context"),
                        "llm_suggestion": de_.get("llm_suggestion")},
                    "s7": None if ad_ is None else {
                        "admit": ad_.get("admit"), "channel": ad_.get("channel"), "char": ad_.get("char"),
                        "reading": ad_.get("reading"), "provenance": ad_.get("provenance"),
                        "doubts": ad_.get("doubts"), "evidence": ad_.get("evidence")},
                })
        big = 10 ** 6
        prow.sort(key=lambda x: (x["col"], x["col_order"] if x["col_order"] is not None else big, x["slot"]))
        for i, x in enumerate(prow, 1):
            x["page_order"] = i
        rows.extend(prow)
    for i, x in enumerate(rows, 1):
        x["seq"] = i
    with open(a.out, "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    miss = {k: sum(1 for x in rows if x[k] is None) for k in ("s5a", "s5c_ocr", "s5b_rare", "s5d", "s6", "s7")}
    print(json.dumps({"rows": len(rows), "pages": len(chars), "missing": miss, "out": a.out},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
