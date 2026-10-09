# -*- coding: utf-8 -*-
"""窄列放行量（overview#493，只量不改 steps/）：页内列宽 < 0.75×该页列宽中位数 的列上，已放行格有多少、集中在哪些页、有标签对错。
用法：python narrow_col_admit.py <seed_admit 导出 jsonl> <column_gate 目录（含 p*.json）> <册名> [gold2.jsonl]
列宽取 column_gate 产物的每列 band_width，页中位取该页 column_widths 的中位（产物里有 median_width 就用它）。
注意：column_gate 产物须与导出同几何（格号一致）；脚本会报两边格号一致率。"""
import json, sys, glob, os, collections, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ex_f, cg_dir, book = sys.argv[1:4]
gold_f = sys.argv[4] if len(sys.argv) > 4 else None
ex = {}
for l in open(ex_f, encoding="utf-8"):
    d = json.loads(l); ex[d["id"]] = d
tr = lambda g: g["shown"] if g["v"] == "ok" else (g.get("char") if g["v"] == "wrong" else None)
L = {}
try:
    from lib import labels
    L = {k: tr(g) for k, g in labels(book).items() if tr(g)}
except Exception:
    pass
if gold_f:
    for l in open(gold_f, encoding="utf-8"):
        g = json.loads(l)
        if tr(g):
            L[g["cell"]] = tr(g)
narrow = {}     # (页, 列) -> (宽, 中位)
for f in sorted(glob.glob(os.path.join(cg_dir, "p*.json"))):
    d = next(iter(json.load(open(f, encoding="utf-8")).values()))
    ws = {c["col"]: c.get("band_width") for c in d.get("columns", []) if c.get("band_width")}
    if not ws:
        continue
    med = d.get("median_width") or statistics.median(ws.values())
    for c, w in ws.items():
        if w < 0.75 * med:
            narrow[(int(d["page"]), c)] = (w, med)
adm = [d for d in ex.values() if d["admit"]]
hit = [d for d in adm if (int(d["id"].split(":")[1]), int(d["id"].split(":")[2])) in narrow]
cols_in_ex = {(int(k.split(":")[1]), int(k.split(":")[2])) for k in ex}
print(f"{book}：窄列 {len(narrow)} 个（其中导出里有格的 {sum(1 for c in narrow if c in cols_in_ex)}）；窄列上放行 {len(hit)} 格／全部放行 {len(adm)}（{100*len(hit)/max(1,len(adm)):.2f}%）")
pg = collections.defaultdict(list)
for d in hit:
    pg[int(d["id"].split(":")[1])].append(d)
for p, ds in sorted(pg.items(), key=lambda kv: -len(kv[1])):
    cols = sorted({int(d["id"].split(":")[2]) for d in ds})
    lab = [(d["id"], d["char"], L[d["id"]]) for d in ds if d["id"] in L]
    ok = sum(1 for _, a, b in lab if a == b)
    ws = ",".join(f"c{c}:{narrow[(p, c)][0]:.0f}/{narrow[(p, c)][1]:.0f}" for c in cols)
    print(f"p{p}｜放行{len(ds)}｜列 {ws}｜有标签 对{ok}/错{len(lab)-ok}" + (f" 错例{[x for x in lab if x[1]!=x[2]][:3]}" if len(lab) > ok else ""))
