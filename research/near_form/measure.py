"""形近字组：量各通道/各来源的首选字错率（overview#428）。用法：python measure.py items.jsonl"""
import json, sys
from collections import defaultdict
G = {"jys": set("己已巳"), "ry": set("日曰"), "rr": set("入人八")}
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
# 真值档：strong = 人裁 / 看图；weak = 证人一致（只作参考，对 match_ref 是循环的）
def strong(r): return r["gold"] and r["gold_src"] not in (None, "witness_agree")
def pick(r, src):
    if src == "ref": return r["ref"] or r["coord_ref"]
    if src == "lib": return r["lib"][0][0] if r["lib"] else None
    if src == "ctx": return r["ctx"]
    if src == "ocr": return r["ocr"][0][0] if r["ocr"] else None
    if src == "jys_rule": return (r["ji_yi_si"] or {}).get("char")
    if src == "admitted": return r["char"] if r["admit"] and r["channel"] != "human" else None
tab = defaultdict(lambda: [0, 0])
for r in rows:
    if not strong(r): continue
    gset = G[r["group"]]
    if r["gold"] not in gset: continue
    for src in ("ref", "lib", "ctx", "ocr", "jys_rule", "admitted"):
        c = pick(r, src)
        if c is None or c not in gset: continue   # 该来源在本组上没有给出组内的字，不计
        k = (r["group"], r["book"], src)
        tab[k][1] += 1; tab[k][0] += (c != r["gold"])
    if r["admit"] and r["channel"] not in (None, "human") and r["char"] in gset:
        k = (r["group"], r["book"], "ch:" + r["channel"])
        tab[k][1] += 1; tab[k][0] += (r["char"] != r["gold"])
for k in sorted(tab):
    e, n = tab[k]; print(*k, f"{e}/{n}", f"{100*e/n:.1f}%")
n = defaultdict(int)
for r in rows:
    if strong(r): n[(r["group"], r["book"])] += 1
print("强真值格数", dict(n))
