# -*- coding: utf-8 -*-
"""M7 IDS 扩展：用已标格建模板库，对一组全部 core 格出证据（自动缝 + 模板最近邻）。

    python research/m7/ids2/predict_two.py <can> <cells.json> <done.jsonl> <crops_dir> <out_evidence.json> [min_margin]
证据字段同 yi_ids_vol04.json：id/ids/char/kind/flag/slots/margins；另附 ref（整理本字）、admit（放行字）、labeled（是否在训练里）。
已标格自己判时用留一的库。
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups import ids_two as T
from open_guji_cv.groups.ids import IdsResolver

CFG = {"shen": dict(members="慎愼", orient="v", prior=0.33, frame="⿰忄{}", dir="config/groups/shen"),
       "can": dict(members="參㕘", orient="h", prior=0.52, frame="⿱厽{}", dir="config/groups/can")}
g, cells, done, crops, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])
mm = float(sys.argv[6]) if len(sys.argv) > 6 else 0.02
c = CFG[g]; rs = IdsResolver(list(c["members"]), c["dir"])
lab = {r["id"]: r for r in map(json.loads, open(done, encoding="utf-8")) if r["f"] in c["members"] and len(r["p"]) >= 2}
img = lambda i: np.asarray(Image.open(crops / (i.replace(":", "_") + ".png")).convert("L"))
G = {i: img(i) for i in lab}
rows = [r for r in json.load(open(cells, encoding="utf-8")) if r["core"] and r["group"] == g]
ev = []
for r in rows:
    i = r["id"]; gray = G[i] if i in G else img(i)
    bank = {}
    for o in lab.values():
        if o["id"] != i: T.add_real(bank, G[o["id"]], T.slot_name(rs, o["f"], c.get("which", 1)), o["p"], c["orient"], c.get("which", 1))
    v = T.solve_two(gray, bank, rs, c["frame"], c["orient"], c["prior"], which=c.get("which", 1), min_margin=mm)
    ev.append({"id": i, "ids": v.ids, "char": v.char, "kind": v.kind, "flag": v.flag, "slots": list(v.slots),
               "margins": list(v.margins), "ref": r["ref"], "admit": r["admit_char"], "labeled": i in lab, "gold": lab[i]["f"] if i in lab else None})
json.dump(ev, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
n = len(ev); gave = [e for e in ev if e["char"]]
print("cells", n, "gave", len(gave), "abstain", n - len(gave))
ref = lambda e: e["ref"] or e["admit"]
print("agree with ref/admit:", sum(1 for e in gave if e["char"] == ref(e)), "disagree:", sum(1 for e in gave if ref(e) and e["char"] != ref(e)))
