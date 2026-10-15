# -*- coding: utf-8 -*-
"""从语料（daizhige，与《總目》无重叠）挖「已＋X」「X＋已」规则的候选（overview#443，10-10）。

数「己已巳字位 + 后一字 / 前一字」的三字计数。语料里「巳」多是「已」的讹写，「己」在「已久」「已經」等处也常是讹写，
所以看已＋巳占比（不是严格的已纯度），再人工读「己」的例子筛。用法：mine_yi_rules.py [minn=30] [pur=0.97]
输出：候选 X 及计数；入选的见 `open_guji_cv/utils/ji_yi_si_clf.py` 的 YI_NEXT2 / YI_PREV2。"""
import collections, re, sys
from pathlib import Path

CV = Path(__file__).resolve().parents[3]
minn = int(sys.argv[1]) if len(sys.argv) > 1 else 30
pur = float(sys.argv[2]) if len(sys.argv) > 2 else 0.97
t = "".join((CV / f"corpus/external/daizhige_{n}.txt").read_text(encoding="utf-8") for n in ("ru_yi", "zhaoling")).replace("\r", "")
t = re.sub(r"\n+", "|", t)
side = {"next": collections.defaultdict(lambda: [0, 0, 0]), "prev": collections.defaultdict(lambda: [0, 0, 0])}
for m in re.finditer("[己已巳]", t):
    i = m.start(); k = "己已巳".index(t[i])
    if i + 1 < len(t): side["next"][t[i + 1]][k] += 1
    if i: side["prev"][t[i - 1]][k] += 1
for s, d in side.items():
    print("==", s)
    for x, c in sorted(d.items(), key=lambda kv: -sum(kv[1])):
        n = sum(c)
        if n >= minn and (c[1] + c[2]) / n >= pur and c[0] > 0 and x not in "朔初":
            print(x, n, c, round((c[1] + c[2]) / n, 3))
