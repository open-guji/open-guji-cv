"""ry／rm L1 规则对 vol11–20 全部日曰目格（回放输出）回测：命中给字与真值不同的列出来。
真值＝逐格细读（dataset labels.jsonl）；没细读的格＝放行字（1888 格逐格扫过，错的已进 verdicts）。
用法：python l1_check.py <回放 jsonl> labels.jsonl [规则目录，缺省 config/groups]"""
import collections
import json
import sys
from pathlib import Path

from open_guji_cv.groups.ctx_l1 import CtxL1Backend

rp, vp = sys.argv[1:3]
rd = Path(sys.argv[3] if len(sys.argv) > 3 else "config/groups")
V = {(v := json.loads(l))["id"]: {**v, "char": v.get("char", v.get("form"))} for l in open(vp, encoding="utf-8")}
B = {g: CtxL1Backend(rd / g / "rules.yaml") for g in ("ry", "rm")}
MEM = {"ry": "日曰", "rm": "日目"}
hit = collections.Counter()
bad = collections.Counter()
for l in open(rp, encoding="utf-8"):
    r = json.loads(l)
    o = r.get("orig") or {}
    v = V.get(r["id"])
    truth = v["char"] if v else (o.get("char") if o.get("admit") else (r.get("later") or {}).get("char"))
    if truth is None:
        continue
    for g, b in B.items():
        ch, why, ids = b.decide(r["left"], r["right"])
        if ch is None:
            continue
        key = (g, ",".join(ids))
        hit[key] += 1
        want = truth if truth in MEM[g] else "其他"
        if ch != want:
            bad[key] += 1
            print("BAD", g, r["id"], ch, "真值", truth, ids, r["left"][-10:] + "【】" + r["right"][:10])
for k in sorted(hit):
    print(hit[k], bad[k], k)
