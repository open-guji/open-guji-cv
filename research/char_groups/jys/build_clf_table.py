# -*- coding: utf-8 -*-
"""造 seed_admit `ji_yi_si_clf_table` 答案表（overview#443 段 2）。

输入：dataset char-groups/jys/items.jsonl（上下文）+ llm_judge/*.out.json（离线盲判，一格可有多遍）。
输出：dataset char-groups/jys/clf_table.json  {"cells": {id: {ctx, llm:[遍1,遍2], lr, lr_p, lr_margin, passes}}}
`ctx` 是 `utils/ji_yi_si_clf.ctx_key(left, right)`——管线里上下文对不上就不采信（ctx_mismatch）。
遍的取法：按文件前缀顺序 p1,p2,f1,f2,g1,g2,pool，取前两遍。语料分类器是离线训的（sklearn），所以随表带进去，管线不再需要它。
用法：build_clf_table.py <llm_dir...>（目录里 *.out.json；缺省只读 dataset llm_judge）"""
import glob, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common, corpus_clf as cc
from open_guji_cv.utils.ji_yi_si_clf import ctx_key

ORDER = ("p1", "p2", "f1", "f2", "g1", "g2", "pool")
dirs = [common.JYS_DIR / "llm_judge"] + [Path(a) for a in sys.argv[1:]]
passes: dict[str, dict[str, str]] = {}
for d in dirs:
    for f in sorted(glob.glob(str(d / "*.out.json"))):
        tag = Path(f).name.split("_")[0]
        for r in json.load(open(f, encoding="utf-8")):
            passes.setdefault(r["id"].replace("_", ":"), {})[tag] = r["char"]
items = [x for x in common.load_items() if x["core"]]
model = cc.train(cache=Path("/tmp/claude-0/jys_clf.pkl"))
P = cc.predict_proba(model, items)
cells = {}
for x, p in zip(items, P):
    got = [passes.get(x["id"], {}).get(t) for t in ORDER]
    got = [g for g in got if g]
    order = sorted(range(3), key=lambda j: -p[j])
    l, r = common.ctx(x)
    cells[x["id"]] = {"ctx": ctx_key(l, r), "llm": (got + [None, None])[:2], "passes": len(got),
                      "lr": cc.FAM[order[0]], "lr_p": round(float(p[order[0]]), 3),
                      "lr_margin": round(float(p[order[0]] - p[order[1]]), 3)}
out = common.JYS_DIR / "clf_table.json"
out.write_text(json.dumps({"doc": "ji_yi_si_clf 答案表（overview#443）：大模型盲判前两遍 + 语料分类器；ctx=utils.ji_yi_si_clf.ctx_key",
                           "cells": cells}, ensure_ascii=False, indent=0), encoding="utf-8")
n2 = sum(1 for c in cells.values() if c["passes"] >= 2)
print(len(cells), "格，两遍以上", n2, "→", out)
