# -*- coding: utf-8 -*-
"""串联评测：规则 → 语料分类器 → 大模型（两遍）。策略在 dev 上选，冻结后 val/vol05 一次性报。
用法：cascade.py <llm_dir> dev|val|vol05|all
"""
import sys, pickle
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common, corpus_clf as cc, rules, llm_eval as le

LLM = sys.argv[1]
which = sys.argv[2]
sets = {"dev": common.DEV, "val": common.VAL, "vol05": common.POOL_GOLD}
model = cc.train(cache=Path("/tmp/claude-0/jys_clf.pkl"))
rows = [x for x in common.strong(common.load_items()) if which == "all" or x["book"] in sets[which]]
P = cc.predict_proba(model, rows)
r1, r2 = le.load(LLM, "p1"), le.load(LLM, "p2")
TH = 0.9


def policies(x, p):
    rule = rules.classify(*common.ctx(x))[0]
    lr = cc.FAM[int(p.argmax())]; lrp = float(p.max())
    a, b = r1.get(x["id"], {}).get("char"), r2.get(x["id"], {}).get("char")
    llm = a if a and a == b else None            # 两遍一致才算
    out = {"规则": rule, "规则→LR": rule or (lr if lrp >= TH else None), "LLM两遍一致": llm}
    # S1: 规则 → LLM 两遍一致且 LR 同意
    out["S1 规则→(LLM∧LR同)"] = rule or (llm if llm and llm == lr else None)
    # S2: 规则 → LLM两遍一致
    out["S2 规则→LLM一致"] = rule or llm
    # S3: 规则 → LR≥0.9 → LLM一致
    out["S3 规则→LR→LLM一致"] = rule or (lr if lrp >= TH else None) or llm
    # S4: 规则 → (LR≥0.9 且 LLM 一致且同) 否则 LLM∧LR 同
    out["S4 规则→LR与LLM同意"] = rule or (llm if llm and llm == lr and lrp >= 0.5 else None)
    return out


res = {}
for x, p in zip(rows, P):
    for k, v in policies(x, p).items():
        res.setdefault(k, {})[x["id"]] = v
for k, pred in res.items():
    print(f"[{which}] {k:22s}", common.fmt(common.metrics(rows, pred)))
if which != "dev" or "-v" in sys.argv:
    for k in ("S1 规则→(LLM∧LR同)", "S3 规则→LR→LLM一致"):
        for b, m in common.by_book(rows, res[k]).items(): print("   ", k, b, common.fmt(m))
if "-e" in sys.argv:
    k = sys.argv[sys.argv.index("-e") + 1]
    for x in rows:
        v = res[k][x["id"]]
        if v and v != x["gold"]: print("  错", x["id"], x["gold"], v, common.ctx(x, 6))
