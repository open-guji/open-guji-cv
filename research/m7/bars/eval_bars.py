"""量两横长短：土士、未末。读 m7-ext 的字块图与标签，按阈值报给字/弃权/对错。
用法：python research/m7/bars/eval_bars.py <m7-ext 目录>
强真值＝human_gold_events.json + 复审页裁决（verdicts_*.jsonl）；弱真值＝上下文路 final（L1/haiku）。
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import bars

R = Path(sys.argv[1])
cells = json.load(open(R / "cells_with_crops.json"))
strong = dict(json.load(open(R / "human_gold_events.json")))
for f in R.glob("verdicts_*.jsonl"):
    for l in f.open(encoding="utf-8"):
        j = json.loads(l)
        if j["verdict"] in "土士未末":
            strong[j["id"]] = j["verdict"]


def ratio(path):
    m = bars.main_cc(bars.ink(bars.load(str(path))))
    if m is None:
        return None
    b, _ = bars.bars(m)
    if len(b) < 2:
        return None
    t = sorted(sorted(b, key=lambda x: -x[2])[:2], key=lambda x: x[0])
    return t[1][2] / t[0][2]  # 下横/上横：>1 是土、未；<1 是士、末


rows = [(c, ratio(R / c["crop"])) for c in cells]
for g, (a, b) in (("ts", "土士"), ("wm", "未末")):
    for lo, hi in ((0.95, 1.05), (0.9, 1.1), (0.85, 1.15)):
        for name, lab in (("强", lambda c: strong.get(c["id"])), ("弱", lambda c: c["final"])):
            n = ab = ok = 0
            for c, r in rows:
                t = lab(c)
                if c["group"] != g or t not in (a, b):
                    continue
                n += 1
                if r is None or lo < r < hi:
                    ab += 1
                    continue
                ok += (a if r >= hi else b) == t
            print(f"{g} 弃权带[{lo},{hi}] {name}真值 n={n} 弃权={ab} 给字对={ok}/{n-ab}")
