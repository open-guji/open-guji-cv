"""a6b：自举学习曲线——每字只放 K 个全唐文人裁刻例进库（siku+qtw），
测试集换成**另一来源**：维基锚定格（qtw_corpus.pkl）里真值字属于这 37 个字、且所在页不在
训练页里的格。这样避开「人裁格来自按形聚类的整簇确认、彼此天然相像」的自相似偏差。
  python a6b_bootstrap_curve.py <qtw_human.pkl> <qtw_corpus.pkl> <out.json> [variant]
"""
from __future__ import annotations

import collections
import json
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from a1_score_dist import rel  # noqa: E402
from a4_rematch import QTW_SIZE, SIKU_SIZE, make_variants  # noqa: E402
from a6_bootstrap import build  # noqa: E402


def page(i):
    return ":".join(i.split(":")[:2])


def main():
    hp, cp, out = sys.argv[1:4]
    pos = [a for a in sys.argv[4:] if not a.startswith("--")]
    var = pos[0] if pos else "base"
    V = make_variants(SIKU_SIZE / QTW_SIZE)[var]
    H = pickle.load(open(hp, "rb")); C = pickle.load(open(cp, "rb"))
    chars = {r["truth"] for r in H}
    train_pages = {page(r["id"]) for r in H}
    test = [r for r in C if any(rel(r["truth"], c) for c in chars) and page(r["id"]) not in train_pages]
    # 测试集太小就放宽：只排除同格
    if len(test) < 150:
        hid = {r["id"] for r in H}
        test = [r for r in C if any(rel(r["truth"], c) for c in chars) and r["id"] not in hid]
    by = collections.defaultdict(list)
    if "--holdout-human" in sys.argv:
        # 测试 = 人裁集按页留出 30%（难例子集，但与训练同源、偏自相似）
        pages = sorted({page(r["id"]) for r in H}); random.Random(0).shuffle(pages)
        tp = set(pages[: int(len(pages) * 0.3)])
        test = [r for r in H if page(r["id"]) in tp]
        H = [r for r in H if page(r["id"]) not in tp]
        res_mode = "holdout-human"
    else:
        res_mode = "corpus"
    tn = [(r["id"], r["truth"], V(r["img"], bool(r.get("punct")))) for r in test]
    for r in H:
        by[r["truth"]].append(r)
    rnd = random.Random(0)
    res = {"mode": res_mode, "variant": var, "n_test": len(tn), "test_chars": len({t for _, t, _ in tn}), "curve": {}}
    for K in (0, 1, 3, 10, 1000):
        rows = []
        for ch, rs in by.items():
            rs = rs[:]; rnd.shuffle(rs)
            rows += [(r["id"], ch, V(r["img"], bool(r.get("punct")))) for r in rs[:K]]
        m = build(rows, siku=True)
        t1 = t5 = 0
        for iid, t, norm in tn:
            cands = [c for c, _ in m.match(norm, exclude_id=iid).candidates[:5]]
            t1 += bool(cands) and rel(cands[0], t); t5 += any(rel(c, t) for c in cands)
        res["curve"][K] = {"lib_add": len(rows), "top1": round(t1 / len(tn), 4), "top5": round(t5 / len(tn), 4)}
        print(K, res["curve"][K], flush=True)
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
