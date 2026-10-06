# -*- coding: utf-8 -*-
"""保守合议：多个模型各自按「训练折内 OOF 正文最高分」定门槛，全部同意才判非正文（AND）。"""
import sys, warnings, json
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.model_selection import StratifiedKFold
from open_guji_cv.pagetype_model import signals as S

d = pd.read_csv(sys.argv[1]); d = d[d.gold != "uncertain"].reset_index(drop=True)
y = (d.gold != "body").astype(int).values
G = lambda g: [f for f in S.FEATURES if S.GROUP_OF[f] in g]
LR = lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000))
HG = lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08, max_iter=150, class_weight="balanced", random_state=0)
MODELS = {"lr_p1": (LR, G({"page", "step1"})), "hgb_p1": (HG, G({"page", "step1"})), "hgb_s1c": (HG, G({"step1", "col"})), "hgb_all": (HG, G({"page","step1","col"}))}
def oof(mk, F, idx, seed=0):
    o = np.zeros(len(idx))
    for a, b in StratifiedKFold(5, shuffle=True, random_state=seed).split(idx, y[idx]):
        m = mk().fit(d.loc[idx[a], F], y[idx[a]]); o[b] = m.predict_proba(d.loc[idx[b], F])[:, 1]
    return o
def vote(names, tr, te, margin):
    pred = np.ones(len(te), bool)
    for n in names:
        mk, F = MODELS[n]
        o = oof(mk, F, tr); thr = min(1.0, o[y[tr] == 0].max() + margin)
        m = mk().fit(d.loc[tr, F], y[tr]); pred &= m.predict_proba(d.loc[te, F])[:, 1] > thr
    return pred
d["_blk"] = d.groupby("book").page.transform(lambda p: pd.qcut(p.rank(method="first"), 5, labels=False))
out = {}
for names in (["hgb_s1c"], ["lr_p1", "hgb_p1"], ["lr_p1", "hgb_p1", "hgb_s1c"], ["lr_p1","hgb_all"]):
    for margin in (0.0, 0.02):
        for kind in ("page", "block"):
            fp = n_b = tp = n_n = 0; by = {}
            seeds = range(3) if kind == "page" else [0]
            for sd in seeds:
                splits = (StratifiedKFold(5, shuffle=True, random_state=sd).split(d, d.gold) if kind == "page"
                          else [(np.where(d._blk != b)[0], np.where(d._blk == b)[0]) for b in range(5)])
                for tr, te in splits:
                    tr, te = np.array(tr), np.array(te); p = vote(names, tr, te, margin)
                    yt = y[te]; fp += int((p & (yt == 0)).sum()); n_b += int((yt == 0).sum())
                    tp += int((p & (yt == 1)).sum()); n_n += int((yt == 1).sum())
                    for g in set(d.gold[te][yt == 1]):
                        m = (d.gold.values[te] == g); c = by.setdefault(g, [0, 0]); c[0] += int(p[m].sum()); c[1] += int(m.sum())
            r = {"models": "+".join(names), "margin": margin, "cv": kind, "body_FP": fp, "body_n": n_b, "nonbody_TP": tp, "nonbody_n": n_n,
                 "by_class": {g: f"{a}/{b}" for g, (a, b) in sorted(by.items())}}
            out[f"{r['models']}|{margin}|{kind}"] = r; print(json.dumps(r, ensure_ascii=False), flush=True)
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
