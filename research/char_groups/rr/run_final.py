"""定稿评测：rf（24×24 投影网格+行列投影+顶部结构）、hand（只用 7 个手工结构特征的 rf）。
训练只用弱标签（dev vol02/03 + pool vol05–10，不含强真值格、不含 vol04）；强真值 A/B 分开按册报；阈值 0.5/0.8 事先定，不在 vol04 上调。
输出 <dataset>/char-groups/rr/clf_eval.json。"""
import json, collections, warnings
import numpy as np
from eval_clf import R, F, strong, weak, TRAIN_BOOKS, CLS, DS
from sklearn.ensemble import RandomForestClassifier
HAND = slice(-7, None)
tr = [r for r in R if weak(r) and r["id"] in F and r["book"] in TRAIN_BOOKS]
y = [CLS.index(r["char"]) for r in tr]
X = np.array([F[r["id"]] for r in tr])
M = {"rf": (RandomForestClassifier(300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1), slice(None)),
     "hand": (RandomForestClassifier(300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1), HAND)}
for m, s in M.values(): m.fit(X[:, s], y)
res = {}
for name, (m, s) in M.items():
    for thr in (0.5, 0.8):
        for bk in ("vol02", "vol03", "vol04"):
            for tier in ("A_human", "B_vision"):
                S = [r for r in R if strong(r) and r["book"] == bk and r["gold_tier"] == tier and r["id"] in F]
                if not S: continue
                P = m.predict_proba(np.array([F[r["id"]][s] for r in S]))
                gave = [(r, CLS[int(p.argmax())]) for r, p in zip(S, P) if p.max() >= thr]
                ok = sum(g == r["gold"] for r, g in gave)
                per = collections.defaultdict(lambda: [0, 0, 0])  # 成员字 → 总/给/对
                for r, p in zip(S, P):
                    per[r["gold"]][0] += 1
                    if p.max() >= thr:
                        per[r["gold"]][1] += 1; per[r["gold"]][2] += CLS[int(p.argmax())] == r["gold"]
                res[f"{name}|{thr}|{bk}|{tier}"] = dict(n=len(S), 给=len(gave), 对=ok, 弃权=len(S) - len(gave),
                    错=[(r["id"], r["gold"], g) for r, g in gave if g != r["gold"]], 按字=dict(per))
for k, v in res.items(): print(k, v["n"], "给", v["给"], "对", v["对"], "弃", v["弃权"], v["错"], dict(v["按字"]))
json.dump(res, open(DS + "/clf_eval.json", "w"), ensure_ascii=False, indent=1)
