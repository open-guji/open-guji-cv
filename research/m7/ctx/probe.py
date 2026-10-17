"""快速探一条正则：python probe.py <组> <字> '<re>' → 强/弱真值上命中、对、错 + 错例。"""
import re, sys
from common import *
g, ch, pat = sys.argv[1:4]; P = re.compile(pat); fam = set(FAMILY[g])
for tiers in (STRONG, ("C_weak",)):
    hit = ok = 0; errs = []
    for r in load(g):
        if r["gold_tier"] not in tiers or r["gold"] not in fam: continue
        l, rr = window(r)
        if P.search(l + "◎" + rr):
            hit += 1
            if r["gold"] == ch: ok += 1
            else: errs.append((r["id"], r["gold"], l[-8:] + "【】" + rr[:8]))
    print(tiers, "hit", hit, "ok", ok, "err", hit - ok)
    for e in errs[:12]: print("   ", e)
