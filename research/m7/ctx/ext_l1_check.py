"""扩展字组 L1 规则对账：规则给字 vs 整理本字（整理本不是真值，冲突格要逐格看窗口）。
  python ext_l1_check.py <cells.jsonl> <组> [--show]"""
import json, sys, collections
sys.path.insert(0, "/home/user/open-guji-cv")
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
cells_f, g = sys.argv[1], sys.argv[2]
b = CtxL1Backend(f"/home/user/open-guji-cv/config/groups/{g}/rules.yaml")
cells = [json.loads(l) for l in open(cells_f, encoding="utf-8")]
cells = [c for c in cells if c["group"] == g]
give = conf = 0; byrule = collections.defaultdict(lambda: [0, 0]); bad = []
for c in cells:
    ch, why, ids = b.decide(c["left"], c["right"])
    if ch is None: continue
    give += 1
    for i in ids: byrule[i][0] += 1
    if ch != c["ref"]:
        conf += 1; bad.append((c["id"], c["ref"], ch, ids, c["left"][-8:] + "【" + c["ref"] + "】" + c["right"][:8]))
        for i in ids: byrule[i][1] += 1
print(g, "格", len(cells), "L1给字", give, "与整理本冲突", conf)
for k, (n, e) in sorted(byrule.items()): print(f"  {k}: {n} 格, 冲突 {e}")
for x in bad: print("  CONFLICT", x)
