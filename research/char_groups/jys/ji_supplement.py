# -*- coding: utf-8 -*-
"""己方向补抽清单（overview#443/#437 Mila 10-11 要求，≥60 格）：给 Lucian 对在线/整理本原文勘字用（独立于图像与分类器）。
抽样框：vol02–10 core 格，无人裁真值；B 组＝规则不命中、大模型两遍/分类器含「己」（全收）；A 组＝规则判己（按规则类分层抽）。
种子固定。输出 dataset char-groups/jys/ji_supplement_1011.{json,md}。"""
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import common
from open_guji_cv.utils import ji_yi_si_clf as clf

t = json.load(open(common.JYS_DIR / "clf_table.json", encoding="utf-8"))["cells"]
items = [x for x in common.load_items() if x["core"] and x["book"] != "vol01" and x["gold_tier"] != "A_human"]
A, B = {}, []
for x in items:
    l, r = common.ctx(x)
    rule, why = clf.classify(l, r)
    c = t.get(x["id"], {})
    sig = [s for s in (c.get("llm") or []) if s] + ([c["lr"]] if c.get("lr") else [])
    if rule == "己":
        A.setdefault(why, []).append((x, why, sig))
    elif not rule and "己" in sig:
        B.append((x, "无规则:大模型/分类器含己", sig))
rng = random.Random("20261011:ji")
quota = {"搭配:己意类": 10, "搭配:以己見类": 8, "干支:后地支": 6, "干支:后地支(日期语境)": 4, "搭配:自己类": 5}
pick = list(B)
for k, n in quota.items():
    pool = sorted(A.get(k, []), key=lambda z: z[0]["id"])
    pick += rng.sample(pool, min(n, len(pool)))
rows = []
for x, why, sig in sorted(pick, key=lambda z: z[0]["id"]):
    l, r = common.ctx(x, 15)
    rows.append({"id": x["id"], "book": x["book"], "page": x["page"], "col": x["col"], "slot": x["slot"], "group": why,
                 "signals": sig, "左15": l, "右15": r, "看图结论": x["gold"] if x["gold_tier"] == "B_vision" else None,
                 "原文所见字": None, "出处": None})
out = common.JYS_DIR
(out / "ji_supplement_1011.json").write_text(json.dumps({"doc": "己方向补抽清单：每格请对在线/整理本原文读出该位的字并记出处（与看图判分开记）",
                                                          "n": len(rows), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
md = ["| # | id | 组 | 信号(LLM/LR) | 上下文 |", "|---|---|---|---|---|"]
for i, r in enumerate(rows, 1):
    md.append(f"| {i} | {r['id']} | {r['group'].replace('搭配:','').replace('干支:','干支·')} | {''.join(r['signals'])} | {r['左15']}【?】{r['右15']} |")
(out / "ji_supplement_1011.md").write_text("\n".join(md), encoding="utf-8")
import collections
print(len(rows), collections.Counter(r["group"] for r in rows), len(B), {k: len(v) for k, v in A.items()})
