# -*- coding: utf-8 -*-
"""Step6 形近／字组分类器接线的可行性回放（只读，不改 steps/）。

用法：python step6_sim.py <重放 seed_admit 产物根> <快照 products 根> <book> <金标 jsonl> <输出前缀>

对重放产物里仍待审的格逐格抽关系证据，分成：
  covered   组表（variant_tie 6 组）里的字，却没放——卡在 cov／近邻条件，不是缺组；
  variant   top1 与整理本字（对位或坐标）是 variants.json 里的**直接边**（异体对）；
  near      top1／整理本字／上下文首位之间有形近对手关系（NEAR_FORM、confusable.partners）；
  none      以上都不是（库没字、margin 不足无关系等）→ 分类器管不着，只能人审。
并附上看图标签（labels_<book>.jsonl，整理看图＋用户裁决合并后的金标 gold2）能给的「真字」，
测几条朴素接线规则的放行数与误放行数。"""
import json, sys, collections
sys.path.insert(0, __import__("os").path.dirname(__file__))
from lib import load_step
from cls import cls_of
from open_guji_cv import variants as V
from open_guji_cv.clustering import confusable
from open_guji_cv.clustering.seeding import NEAR_FORM_CHARS

GROUPS = "𫎇蒙䝉,㸃點,㕘參,䜟讖識,𨽾隸,慎愼".split(",")
GCH = set("".join(GROUPS))
prod, src, book, gold_f, outp = sys.argv[1:6]

sa = load_step(prod, book, "seed_admit"); gm = load_step(src, book, "glyph_match")
cd = load_step(src, book, "context_decide"); al = load_step(src, book, "align_ref")
gold = {}
for l in open(gold_f, encoding="utf-8"):
    d = json.loads(l); gold[d["cell"]] = d
P = confusable.partners()


def truth(g):
    return g["shown"] if g["v"] == "ok" else (g.get("char") if g["v"] == "wrong" else None)


def near(a, b):
    return bool(a and b and a != b and (b in P.get(a, ()) or a in P.get(b, ())
                or (a in NEAR_FORM_CHARS and b in NEAR_FORM_CHARS)))


rows = []
for k, r in sa.items():
    if r["admit"]:
        continue
    g = gm[k]; c = g["candidates"]; a = al.get(k, {}); d = cd.get(k, {})
    top = c[0][0] if c else None
    ref = a.get("align_char"); op = a.get("align_op")
    cx = (d.get("ranked") or [[None]])[0][0]
    chars = [x for x in (top, ref, cx) if x]
    ing = bool(top and top in GCH and (ref in GCH or ref is None))
    var = any(x != y and V.are_variants(x, y) for x in chars for y in chars if x < y) if len(chars) > 1 else False
    nr = any(near(x, y) for x in chars for y in chars if x < y)
    rel = "covered" if ing else ("variant" if var else ("near" if nr else "none"))
    rows.append(dict(id=k, cls=cls_of(r), rel=rel, top=top, cov=g["cov"], ref=ref, op=op, ctx=cx,
                     top2=c[1][0] if len(c) > 1 else None, cov2=c[1][1] if len(c) > 1 else None,
                     gold=(truth(gold[k]) if k in gold else "?")))

json.dump(rows, open(outp + ".json", "w"), ensure_ascii=False)
cnt = collections.Counter(r["rel"] for r in rows)
print(book, "待审", len(rows), dict(cnt))
bycls = collections.defaultdict(collections.Counter)
for r in rows:
    bycls[r["rel"]][r["cls"]] += 1
for rel, cc in bycls.items():
    print(" ", rel, dict(cc.most_common(6)))
lab = [r for r in rows if r["gold"] != "?" and r["gold"] is not None]
print("有金标的待审格", len(lab), collections.Counter(r["rel"] for r in lab))
for rel in ("covered", "variant", "near", "none"):
    xs = [r for r in lab if r["rel"] == rel]
    if not xs:
        continue
    t = sum(r["gold"] == r["top"] for r in xs); f = sum(r["gold"] == r["ref"] for r in xs)
    both = sum(r["top"] == r["ref"] == r["gold"] for r in xs)
    print(f"  {rel}: 金标字=库top1 {t}/{len(xs)}，=整理本字 {f}/{len(xs)}，top1==整理本==金标 {both}")
