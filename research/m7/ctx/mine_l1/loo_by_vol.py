"""按册留出：判某册时规则只从其余册挖（两半各 ≥2、零冲突），拿去判该册已放行格与整理本字，数给字与冲突。"""
import json, collections, re
GROUPS = {"zy": "于千子干", "yz": "予子", "guan": "官宫宮", "hou": "侯候𠉀俟", "liang": "兩雨"}
FAM = {"宮": "宫", "𠉀": "候"}
import sys
K = int(sys.argv[1]); DIG = set("一二三四五六七八九十百千萬廿卅") if sys.argv[2] == "1" else set()
rows = [json.loads(l) for l in open("cells.jsonl")]
vols = sorted({r["vol"] for r in rows})
def feats(L, R):
    out = []
    if len(L) >= 2 and "□" not in L[-2:]: out.append(L[-2:] + "◎")
    if len(R) >= 2 and "□" not in R[:2]: out.append("◎" + R[:2])
    if L and R and "□" not in L[-1] + R[0]: out.append(L[-1] + "◎" + R[0])
    return out
res = collections.defaultdict(collections.Counter)
for g, mem in GROUPS.items():
    adm = [r for r in rows if r["admit"] and r["char"] in mem]
    for v in vols:
        tr = [r for r in adm if r["vol"] != v]
        rest = [x for x in vols if x != v]; A = set(rest[:len(rest)//2])
        st = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        for r in tr:
            for f in feats(r["left"], r["right"]): st[f]["a" if r["vol"] in A else "b"][FAM.get(r["char"], r["char"])] += 1
        rules = {}
        for f, hh in st.items():
            tot = hh["a"] + hh["b"]
            if len(tot) == 1:
                ch = next(iter(tot))
                if hh["a"][ch] >= K and hh["b"][ch] >= K and not (DIG & set(f)): rules[f] = ch
        for r in rows:
            if r["vol"] != v: continue
            labs = ([FAM.get(r["char"], r["char"])] if r["admit"] and r["char"] in mem else []) + ([FAM.get(r["ref"], r["ref"])] if r["ref"] and r["ref"] in mem else [])
            if not labs: continue
            got = {rules[f] for f in feats(r["left"], r["right"]) if f in rules}
            if len(got) != 1: continue
            ch = got.pop(); res[g]["给字"] += 1
            if any(l != ch for l in labs): res[g]["冲突"] += 1; print(g, v, r["id"], labs, ch, r["left"][-6:] + "◎" + r["right"][:6])
for g in GROUPS: print(g, dict(res[g]))
