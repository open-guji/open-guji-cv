"""规则实验台：python lab.py <组> [--misses N] [--errs]
用 config/groups/<组>/rules.yaml 过强真值（A+B）、C 弱真值，按 split 报给字/错；列每条规则的命中与错。"""
import sys, collections, argparse
sys.path.insert(0, "/home/user/open-guji-cv")
from common import *
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.registry import GROUPS

ap = argparse.ArgumentParser(); ap.add_argument("group"); ap.add_argument("--misses", type=int, default=0); ap.add_argument("--rules")
a = ap.parse_args(); g = a.group
spec = GROUPS[g]; fam = set(FAMILY[g]); rows = load(g)
be = CtxL1Backend(a.rules or f"/home/user/open-guji-cv/config/groups/{g}/rules.yaml", spec.members)
print("rules", len(be.rules), "fp", be.fingerprint)
cache = {}
def pick(r):
    if r["id"] not in cache:
        l, rr = window(r); ch, why, ids = be.decide(l, rr); cache[r["id"]] = (ch, why, ids)
    ch, why, ids = cache[r["id"]]; return ch, why + ":" + ",".join(ids)
for nm, t in (("强(A+B)", STRONG), ("C弱", ("C_weak",))):
    s, e = score(rows, pick, g, t); print(nm, s)
    for x in e[:30]: print("   ERR", x)
for sp in ("dev", "val", "pool", "extra"):
    s, _ = score([r for r in rows if r["split"] == sp], pick, g); print(sp, s)
per = collections.defaultdict(lambda: [0, 0, 0])
for r in rows:
    if r["gold_tier"] is None: continue
    pick(r); ch, why, ids = cache[r["id"]]
    for i in ids:
        per[i][0] += 1
        if r["gold"] in fam and ch == r["gold"]: per[i][1] += 1
        elif r["gold"] in fam: per[i][2] += 1
print("规则命中(格)/对/错 [含全部档]:")
for i, (n, o, x) in sorted(per.items(), key=lambda kv: -kv[1][0])[:60]: print(f"  {i:40s} {n:5d} {o:5d} {x:3d}")
if a.misses:
    k = 0
    for r in rows:
        if r["gold_tier"] in STRONG and r["gold"] in fam and not cache[r["id"]][0]:
            l, rr = window(r, 12); print("MISS", r["gold"], r["split"], l + "【" + r["gold"] + "】" + rr); k += 1
            if k >= a.misses: break
