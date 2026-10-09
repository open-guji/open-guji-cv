# -*- coding: utf-8 -*-
"""新留出验证（overview#443 段 1，10-09）：整理看图判定的 vol05 批 1（27 格）与 vol07 批 1（39 格）作留出，另 vol05 批 6/7 的 11 格单列。
冻结 S1（规则 → 大模型两遍一致∧语料分类器同字，否则弃权），不调参。真值＝整理看图（不是用户人裁）。
用法：fresh_eval.py <labels.json> <llm_dir> <out.jsonl>"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common, corpus_clf as cc, rules, llm_eval as le

lab = json.load(open(sys.argv[1], encoding="utf-8")); LLM = sys.argv[2]
items = {x["id"]: x for x in common.load_items()}
model = cc.train(cache=Path("/tmp/claude-0/jys_clf.pkl"))
ids = sorted(lab)
P = cc.predict_proba(model, [items[i] for i in ids])
p1, p2 = le.load(LLM, "f1"), le.load(LLM, "f2")
out = []
for i, p in zip(ids, P):
    x = items[i]
    rule, why = rules.classify(*common.ctx(x))
    order = sorted(range(3), key=lambda j: -p[j])
    lr = cc.FAM[order[0]]; margin = float(p[order[0]] - p[order[1]])
    a, b = p1.get(i, {}).get("char"), p2.get(i, {}).get("char")
    llm = a if a and a == b else None
    final, by = (rule, "rule") if rule else ((llm, "llm+lr") if llm and llm == lr else (None, None))
    out.append({"id": i, **lab[i], "rule": rule, "rule_why": why, "lr": lr, "lr_p": round(float(p[order[0]]), 3), "lr_margin": round(margin, 3),
                "llm1": a, "llm2": b, "llm": llm, "final": final, "by": by, "old_admit": items[i].get("admit"), "old_char": items[i].get("char"),
                "old_ref": items[i].get("ref")})
Path(sys.argv[3]).write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")


def rep(name, rows):
    n = len(rows); g = [o for o in rows if o["final"]]; ok = [o for o in g if o["final"] == o["label"]]
    print(f"[{name}] 格 {n}  给字 {len(g)}（{len(g)/n:.0%}）  对 {len(ok)}  错 {len(g)-len(ok)}  准确率 {len(ok)/len(g):.1%}  弃权 {n-len(g)}（{(n-len(g))/n:.0%}）" if g else f"[{name}] 格 {n} 给字 0")
    for r in ("rule", "llm+lr"):
        gg = [o for o in g if o["by"] == r]; k = sum(o["final"] != o["label"] for o in gg)
        print(f"     {r:7s} 给 {len(gg)} 错 {k}")


for s in ("v05b1", "v07b1"):
    rep(s, [o for o in out if o["set"] == s])
rep("留出合计(v05b1+v07b1)", [o for o in out if o["set"] in ("v05b1", "v07b1")])
rep("v05sup 补充", [o for o in out if o["set"] == "v05sup"])
rep("全部", out)
print("\n全部错例：")
for o in out:
    if o["final"] and o["final"] != o["label"]:
        x = items[o["id"]]; l, r = common.ctx(x, 8)
        print(" ", o["id"], "整理看图", o["label"], "给", o["final"], o["by"], o["rule_why"], "lr", o["lr"], o["lr_p"], "llm", o["llm1"], o["llm2"], l + "【?】" + r)
print("\n弃权格：", sum(1 for o in out if not o["final"]))
print("旧管线 默认/放行字 vs 整理看图（留出）：", collections.Counter((o["old_admit"], o["old_char"] == o["label"]) for o in out if o["set"] in ("v05b1", "v07b1")))
