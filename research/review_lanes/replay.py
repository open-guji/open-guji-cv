# -*- coding: utf-8 -*-
"""overview#433（R2）：在快照产物上重放 seed_admit 的待审补放三通道（R1 witness3 / R4 coord_fallback / R5 seal）。

用法：`GUJI_WORKSPACE=<工作区> python research/review_lanes/replay.py <快照>/products/<book> <book> <out.json> [lane_witnesses=... ...]`
快照要带 seed_admit、glyph_match、align_ref（border_detect_gate 有就按正文/非正文分开报）。
重放 = 把快照里的 seed_admit 页读回来，原样跑 `_review_lanes_pass`——上游通道一格不变，
等价于开着开关重落 seed_admit（三通道接在所有现行通道之后，只碰待审格）。"""
import collections, glob, json, os, re, sys
from open_guji_cv.core.book import load_book
from open_guji_cv.products.kinds.recog import PageAdmit
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _lane_class, _lane_witnesses,
                                           _review_lanes_pass)
from open_guji_cv.clustering.variants import VariantMap
from types import SimpleNamespace as NS

root, book_id, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
kw = dict(kv.split("=", 1) for kv in sys.argv[4:] if "=" in kv)
p = SeedAdmitParams(lane_witness3=True, lane_coord=True, lane_seal=True, db_path="x", **kw)
book = load_book(book_id)
vmap = VariantMap.load(None)
ws = _lane_witnesses(book, p)
print("证人:", [w.name for w in ws])


def load(step, pg):
    f = os.path.join(root, step, f"p{pg:04d}.json")
    return next(iter(json.load(open(f, encoding="utf-8")).values())) if os.path.exists(f) else None


res, base = [], collections.Counter()
tot = collections.Counter()
for f in sorted(glob.glob(os.path.join(root, "seed_admit", "p*.json"))):
    pg = int(os.path.basename(f)[1:5])
    sa = PageAdmit.model_validate(load("seed_admit", pg))
    gm = load("glyph_match", pg) or {"columns": []}
    mmap = {r["id"]: NS(char=r.get("char"), candidates=r.get("candidates") or [], guard=r.get("guard"))
            for cc in gm["columns"] if cc.get("ok", True) for r in cc["chars"]}
    ar = load("align_ref", pg) or {}
    amap = {c["id"]: (c["align_char"], c["align_op"]) for c in ar.get("chars", [])} if ar.get("anchored") else {}
    coord = {c["id"]: c.get("ref_char") for c in ar.get("coord", [])}
    g = load("border_detect_gate", pg)
    kind = "body" if g and g.get("page_type") == "body" else "nonbody"
    before = {}
    for cc in sa.columns:
        for r in cc.chars:
            tot[(kind, "cells")] += 1
            if r.admit:
                continue
            lib = (lambda m: (m.char or (m.candidates[0][0] if m.candidates else None)) if m else None)(mmap.get(r.id))
            cls = ("excluded" if "excluded" in r.doubts else
                   _lane_class(r.doubts, r.evidence, r.char, (amap.get(r.id) or (None,))[0], lib))
            before[r.id] = cls
            if cls != "excluded":
                base[(kind, cls)] += 1
    _review_lanes_pass(p, sa.columns, mmap, amap, coord, vmap, lambda: ws)
    for cc in sa.columns:
        for r in cc.chars:
            if r.id in before and r.admit:
                res.append({"id": r.id, "page": pg, "kind": kind, "cls": before[r.id], "lane": r.channel,
                            "char": r.char, **{k: v for k, v in r.evidence["lane"].items() if k != "lane"}})
            elif r.id in before and "lane_skip" in (r.evidence or {}):
                res.append({"id": r.id, "page": pg, "kind": kind, "cls": before[r.id], "lane": "skip:" + r.evidence["lane_skip"]["why"],
                            "char": r.char, "lib": r.evidence["lane_skip"]["lib"]})

for kind in ("body", "nonbody"):
    q = sum(v for (k, c), v in base.items() if k == kind)
    print(f"[{kind}] 字位 {tot[(kind, 'cells')]}，待审 {q}：", {c: v for (k, c), v in sorted(base.items()) if k == kind})
    by = collections.Counter((x["lane"], x["cls"]) for x in res if x["kind"] == kind)
    for (ln, c), v in sorted(by.items()):
        print(f"    {ln:16s} {c:14s} {v}")
    rel = sum(v for (ln, c), v in by.items() if not ln.startswith("skip"))
    print(f"    放行合计 {rel}，剩 {q - rel}（{(q - rel) / max(1, tot[(kind, 'cells')]):.2%}）")
json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
