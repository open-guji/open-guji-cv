"""按组挖 L1 规则：已放行格（vol04–20）按册分两半（04–12／13–20），两半各 ≥2 格、合计 0 冲突的上下文词组。
另把已有规则拿来对全部已放行格回测。"""
import json, collections, re, sys, yaml
GROUPS = {"zy": "于千子干", "yz": "予子", "guan": "官宫宮", "hou": "侯候𠉀俟", "liang": "兩雨"}
FAMILY = {"guan": {"宮": "宫"}, "hou": {"𠉀": "候"}}
rows = [json.loads(l) for l in open("cells.jsonl")]
A = {f"vol{v:02d}" for v in range(4, 13)}
def feats(L, R):
    out = []
    if len(L) >= 2 and "□" not in L[-2:]: out.append(L[-2:] + "◎")
    if len(R) >= 2 and "□" not in R[:2]: out.append("◎" + R[:2])
    if L and R and "□" not in L[-1] + R[0]: out.append(L[-1] + "◎" + R[0])
    return out
DIG = set("一二三四五六七八九十百千萬廿卅")
res = {}
for g, mem in GROUPS.items():
    fm = FAMILY.get(g, {})
    adm = [r for r in rows if r["admit"] and r["char"] in mem]
    stat = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in adm:
        h = "a" if r["vol"] in A else "b"
        ch = fm.get(r["char"], r["char"])
        for f in feats(r["left"], r["right"]): stat[f][h][ch] += 1
    rules = []
    for f, hh in stat.items():
        tot = hh["a"] + hh["b"]
        if len(tot) != 1: continue
        ch = next(iter(tot))
        if hh["a"][ch] >= 3 and hh["b"][ch] >= 3 and not (DIG & set(f)): rules.append((ch, f, hh["a"][ch], hh["b"][ch]))
    res[g] = sorted(rules)
    print(g, len(adm), "cells;", len(rules), "rules", collections.Counter(r[0] for r in rules))
json.dump(res, open("mined.json", "w"), ensure_ascii=False)
