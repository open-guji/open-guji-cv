"""弱标签格上按册留出：分类器（训练不含该册、不含强真值格）与放行字的一致/分歧。分歧格是「可能放行错」的候选。"""
import json, collections, warnings
import numpy as np
from eval_clf import *
out = {}
allbooks = sorted({r["book"] for r in R})
for bk in allbooks:
    trn = [r for r in R if weak(r) and r["id"] in F and r["book"] != bk and r["book"] != "vol04"]
    m = RandomForestClassifier(300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1)
    m.fit(np.array([F[r["id"]] for r in trn]), [CLS.index(r["char"]) for r in trn])
    T = [r for r in R if r["book"] == bk and r["id"] in F and not strong(r)]
    P = m.predict_proba(np.array([F[r["id"]] for r in T]))
    for r, p in zip(T, P):
        out[r["id"]] = [round(float(x), 3) for x in p]
json.dump(out, open(DS + "/clf_loo_probs.json", "w"))
tot = collections.defaultdict(lambda: collections.Counter())
dis = []
for r in R:
    if r["id"] not in out or not r["admit"] or r["char"] not in CLS or strong(r): continue
    p = out[r["id"]]; g = CLS[int(np.argmax(p))]
    for thr in (0.5, 0.8):
        if max(p) >= thr:
            tot[(r["book"], thr)]["给"] += 1; tot[(r["book"], thr)]["同" if g == r["char"] else "异"] += 1
        else: tot[(r["book"], thr)]["弃"] += 1
    if max(p) >= 0.8 and g != r["char"]: dis.append((r["id"], r["char"], g, round(max(p), 2), r["channel"]))
for k in sorted(tot): print(k, dict(tot[k]))
print(len(dis), "分歧(p≥0.8)"); 
for d in dis: print(d)
