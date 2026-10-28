"""按层报表：L1 / L2 / L1→L2 合并（总设计 §6.3：取第一个不弃权的；后者给了不同字 → 弃权 disagree）。
python layers.py <组> <l2 答案表.json>"""
import sys, json
sys.path.insert(0, "/home/user/open-guji-cv")
from common import *
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.ctx_l3 import CtxL3Backend
from open_guji_cv.groups.protocol import JudgeInput, window_from_text
from open_guji_cv.groups.registry import GROUPS
g = sys.argv[1]; spec = GROUPS[g]
l1 = CtxL1Backend(f"/home/user/open-guji-cv/{spec.config_dir}/rules.yaml", spec.members)
l2 = CtxL3Backend(sys.argv[2])
rows = [r for r in load(g)]
tab = json.load(open(sys.argv[2]))["cells"]
rows = [r for r in rows if r["id"] in tab]
def cell(r): return JudgeInput(r["id"], r.get("ref"), window_from_text(*window(r)))
def p1(r): v = l1.judge(spec, cell(r)); return v.char, v.why
def p2(r): v = l2.judge(spec, cell(r)); return v.char, v.why
def pm(r):
    a, b = p1(r)[0], p2(r)[0]
    if a and b and a != b: return None, "disagree"
    return (a or b), ("l1" if a else "l2" if b else "abstain")
for nm, f in (("L1", p1), ("L2", p2), ("L1→L2", pm)):
    s, e = score(rows, f, g)
    print(nm, {k: s[k] for k in ("n", "give", "ok", "err", "cover", "acc", "wilson_lo", "out_of_family", "leak")})
    if nm != "L1":
        for x in e:
            r = next(r for r in rows if r["id"] == x[0]); l, rr = window(r, 10); print("   ERR", x[:3], l + "【" + r["gold"] + "】" + rr, r["gold_tier"], r["gold_src"])
