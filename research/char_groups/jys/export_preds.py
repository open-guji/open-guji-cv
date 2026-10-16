# -*- coding: utf-8 -*-
"""冻结策略 S1（规则 → 大模型∧语料分类器同意）对 jys 全部 core 格出预测，写 dataset char-groups/jys/classifier_preds.jsonl
与 classifier_eval.json。用法：export_preds.py <llm_dir>
策略：规则命中即给字；否则要「大模型（强真值格两遍一致；pool 格只有一遍）」与「语料分类器 argmax」同字才给，其余弃权。
"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common, corpus_clf as cc, rules, llm_eval as le

LLM = sys.argv[1]
model = cc.train(cache=Path("/tmp/claude-0/jys_clf.pkl"))
items = [x for x in common.load_items() if x["core"]]
P = cc.predict_proba(model, items)
p1, p2, pp = le.load(LLM, "p1"), le.load(LLM, "p2"), le.load(LLM, "pool")
out = []
for x, p in zip(items, P):
    i = x["id"]
    rule, why = rules.classify(*common.ctx(x))
    lr = cc.FAM[int(p.argmax())]
    a, b, c = (d.get(i, {}).get("char") for d in (p1, p2, pp))
    if a and b: llm, passes = (a if a == b else None), 2
    elif c: llm, passes = c, 1
    else: llm, passes = None, 0
    if rule: final, by = rule, "rule"
    elif llm and llm == lr: final, by = llm, "llm+lr"
    else: final, by = None, None
    out.append({"id": i, "book": x["book"], "split": x["split"], "gold": x["gold"], "gold_tier": x["gold_tier"],
                "rule": rule, "rule_why": why, "lr": lr, "lr_p": round(float(p.max()), 3),
                "llm": llm, "llm_passes": passes, "final": final, "by": by})
d = common.JYS_DIR
(d / "classifier_preds.jsonl").write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")
strong_ids = {x["id"] for x in common.strong(common.load_items())}
rows = [x for x in common.strong(common.load_items())]
pred = {o["id"]: o["final"] for o in out}
ev = {"policy": "S1: rule -> (llm & lr agree) else abstain", "by_book": common.by_book(rows, pred),
      "by_split": {s: common.metrics([x for x in rows if x["split"] == s], pred) for s in ("dev", "val", "pool", "extra")}}
pool = collections.defaultdict(collections.Counter)
for o in out:
    if o["split"] == "pool" and o["gold_tier"] not in common.STRONG:
        pool[o["book"]]["n"] += 1
        pool[o["book"]]["given_" + (o["by"] or "abstain")] += 1
ev["pool_no_gold_coverage"] = {k: dict(v) for k, v in sorted(pool.items())}
(d / "classifier_eval.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
for b, m in ev["by_book"].items(): print(b, common.fmt(m))
for s, m in ev["by_split"].items(): print(s, common.fmt(m)) if m["n"] else None
print(json.dumps(ev["pool_no_gold_coverage"], ensure_ascii=False))
