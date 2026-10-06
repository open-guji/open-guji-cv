"""在强真值格上量上下文决策表（留出口径）：精度/覆盖。用法：python ctx_eval.py items.jsonl"""
import json, sys
sys.path.insert(0, "research/near_form")
from ctx_table import Table, GROUPS
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
DOM = ["/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本/corpus/zongmu_wenyuange_wikisource.txt"]
EXT = ["corpus/external/daizhige_ru_yi.txt", "corpus/external/daizhige_zhaoling.txt"]
strong = lambda r: r["gold"] and r["gold_src"] not in (None, "witness_agree") and r["gold"] in GROUPS[r["group"]]
for g in GROUPS:
    for name, dom, ext in (("域内+外部(留出)", DOM, EXT), ("仅外部", [], EXT)):
        t = Table(g, dom, ext)
        S = [r for r in rows if r["group"] == g and strong(r)]
        print(f"== {g} {name}")
        for pur, mn in [(0.95, 5), (0.98, 5), (0.99, 10), (1.0, 5)]:
            out = {}
            for bk in ("vol02", "vol03", "vol04", "ALL"):
                sub = [r for r in S if bk == "ALL" or r["book"] == bk]
                dec = err = nob = 0
                for r in sub:
                    ex = t.block_of(r["left"], r["right"]) if dom else None
                    nob += bool(dom) and ex is None
                    ch, why = t.decide(r["left"][-2:], r["right"][:2], pur, mn, ex)
                    if ch: dec += 1; err += ch != r["gold"]
                out[bk] = f"{dec}/{len(sub)}定 错{err}" + (f"(无块{nob})" if nob else "")
            print(f"  purity={pur} n>={mn}:", out)
