# -*- coding: utf-8 -*-
"""通道级误放表（overview#493）：用 seed_admit 逐格导出 × 看图结论 / gold2，按放行通道算 分母与错数。
用法：python channel_false_admit.py <vol05_seed_admit.jsonl> <看图结论.jsonl 所在书名> <gold2.jsonl>
标签优先级：gold2 用户（人裁）＞ gold2 整理看图（模型）＞ 看图结论（模型）。「错」＝放行字≠标签字；
另列「去异体码位差」＝再剔除放行字与标签字是 variants 直接边（口径 A 争议、非认错字）。"""
import json, sys, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import labels
from open_guji_cv import variants as V
ex_f, book, gold_f = sys.argv[1:4]
ex = {}
for l in open(ex_f, encoding="utf-8"):
    d = json.loads(l); ex[d["id"]] = d
tr = lambda g: g["shown"] if g["v"] == "ok" else (g.get("char") if g["v"] == "wrong" else None)
lab = {k: (tr(g), "看图") for k, g in labels(book).items() if tr(g)}
for l in open(gold_f, encoding="utf-8"):
    g = json.loads(l)
    if tr(g):
        lab[g["cell"]] = (tr(g), "人裁" if g.get("src") == "用户" else "看图")
S = collections.defaultdict(lambda: dict(n=0, lab=0, wrong=0, wrong_nonvar=0, h=0, hwrong=0, ex=[]))
for k, d in ex.items():
    if not d["admit"]:
        continue
    s = S[d.get("channel") or "?"]; s["n"] += 1
    if k not in lab:
        continue
    t, src = lab[k]
    s["lab"] += 1
    bad = d["char"] != t
    var = bad and d["char"] and V.are_variants(d["char"], t)
    s["wrong"] += bad; s["wrong_nonvar"] += bad and not var
    if bad:
        s["ex"].append((k, d["char"], t, src, "异体差" if var else ""))
    if src == "人裁":
        s["h"] += 1; s["hwrong"] += bad
print("通道｜放行｜有标签(分母)｜错｜错率｜其中非异体码位差｜人裁(分母)｜人裁错")
tot = collections.Counter()
for c, s in sorted(S.items(), key=lambda kv: -kv[1]["n"]):
    r = f"{100*s['wrong']/s['lab']:.1f}%" if s["lab"] else "-"
    print(f"{c}｜{s['n']}｜{s['lab']}｜{s['wrong']}｜{r}｜{s['wrong_nonvar']}｜{s['h']}｜{s['hwrong']}", s["ex"])
    for k in ("n", "lab", "wrong", "wrong_nonvar", "h", "hwrong"):
        tot[k] += s[k]
print("合计", dict(tot))
