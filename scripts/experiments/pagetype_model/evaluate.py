# -*- coding: utf-8 -*-
"""正文/非正文二分：LR / HGB vs 现行规则；按册留出 + 按页分组折 + 块折 + 消融。

非正文 = 金标 != body（uncertain 剔除）。零容忍正文误判：门槛 = 训练折内 OOF 正文得分的最大值
（再加余量），不看测试折。
"""
from __future__ import annotations

import argparse
import json
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from open_guji_cv.pagetype_model import signals as S

warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--feats", required=True)
ap.add_argument("--json-out")
a = ap.parse_args()
d = pd.read_csv(a.feats)
d = d[d.gold != "uncertain"].reset_index(drop=True)
y = (d.gold != "body").astype(int).values
RARE = {"cover", "label", "colophon", "edict"}   # 极少类：保留现行规则，不进模型评价
d["rare"] = d.gold.isin(RARE)


def mk(kind):
    if kind == "lr":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000))
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08, max_iter=150,
                                          class_weight="balanced", random_state=0)


def fit_score(kind, feats, tr, te):
    m = mk(kind)
    Xtr = d.loc[tr, feats]
    m.fit(Xtr, y[tr])
    return m, m.predict_proba(d.loc[te, feats])[:, 1]


def oof_scores(kind, feats, idx, seed=0, k=5):
    """idx 内的折外得分（用来定门槛，不碰测试集）。"""
    out = np.zeros(len(idx))
    skf = StratifiedKFold(k, shuffle=True, random_state=seed)
    for a_, b_ in skf.split(idx, y[idx]):
        _, s = fit_score(kind, feats, idx[a_], idx[b_])
        out[b_] = s
    return out


def threshold(kind, feats, tr, margin=0.0):
    """门槛 = 训练集内 OOF 里正文最高得分 + margin（零训练内正文误判）。"""
    o = oof_scores(kind, feats, tr)
    body = o[y[tr] == 0]
    return min(1.0, float(body.max()) + margin) if len(body) else 1.0


def report(name, te, score, thr):
    pred = score > thr
    yt = y[te]
    body = yt == 0
    nb = yt == 1
    sub = d.loc[te]
    r = {"name": name, "n": int(len(te)), "thr": round(float(thr), 4),
         "body_n": int(body.sum()), "body_FP": int((pred & body).sum()),
         "body_recall": round(float((~pred[body]).mean()), 4) if body.any() else None,
         "nonbody_n": int(nb.sum()), "nonbody_TP": int((pred & nb).sum()),
         "nonbody_detect": round(float(pred[nb].mean()), 4) if nb.any() else None}
    by = {}
    for g in sorted(set(sub.gold[nb])):
        m = (sub.gold.values == g)
        by[g] = f"{int(pred[m].sum())}/{int(m.sum())}"
    r["by_class"] = by
    return r


GROUPS = {"page": [f for f in S.FEATURES if S.GROUP_OF[f] == "page"],
          "step1": [f for f in S.FEATURES if S.GROUP_OF[f] == "step1"],
          "col": [f for f in S.FEATURES if S.GROUP_OF[f] == "col"]}
ALL = list(S.FEATURES)
res = {}

# 现行规则：非正文 = classify_page_type != body
rule_pred = (d.rule_type != "body").values
rr = {"body_FP": int((rule_pred & (y == 0)).sum()), "body_n": int((y == 0).sum()),
      "nonbody_TP": int((rule_pred & (y == 1)).sum()), "nonbody_n": int((y == 1).sum()),
      "by_class": {g: f"{int(rule_pred[d.gold.values == g].sum())}/{int((d.gold.values == g).sum())}"
                   for g in sorted(set(d.gold[y == 1]))},
      "rule_types": d.groupby(["gold", "rule_type"]).size().to_dict().__repr__()}
res["rule"] = rr
print("现行规则", json.dumps(rr, ensure_ascii=False))

v1 = np.where(d.book == "vol01")[0]
v2 = np.where(d.book == "vol02")[0]
CONFIGS = {"page8": GROUPS["page"], "page8+step1": GROUPS["page"] + GROUPS["step1"],
           "page8+col": GROUPS["page"] + GROUPS["col"], "all": ALL,
           "step1+col": GROUPS["step1"] + GROUPS["col"],
           "small9": ["ink", "n_glyph", "col_ink_mean", "col_updown_min", "col_updown",
                      "col_cover_mean", "period_rel", "y_cover", "col_ink_max"]}
print("\n== 按册留出 ==")
res["cross_book"] = []
for kind in ("lr", "hgb"):
    for cname, feats in CONFIGS.items():
        for trn, tst, nm in ((v1, v2, "vol01→vol02"), (v2, v1, "vol02→vol01")):
            thr = threshold(kind, feats, trn)
            _, s = fit_score(kind, feats, trn, tst)
            r = report(f"{kind}/{cname}/{nm}", tst, s, thr)
            res["cross_book"].append(r)
            print(r["name"], {k: r[k] for k in ("thr", "body_FP", "body_n", "nonbody_TP", "nonbody_n")}, r["by_class"])

print("\n== 页分组折（5折×3种子，分层随机）与块折（页号连续 5 块）==")
res["page_cv"] = []
res["block_cv"] = []
for kind in ("lr", "hgb"):
    for cname, feats in CONFIGS.items():
        tot = {"body_FP": 0, "body_n": 0, "nonbody_TP": 0, "nonbody_n": 0}
        by_tot: dict = {}
        for seed in range(3):
            skf = StratifiedKFold(5, shuffle=True, random_state=seed)
            for tr, te in skf.split(d, d.gold):
                tr = np.array(tr); te = np.array(te)
                thr = threshold(kind, feats, tr)
                _, s = fit_score(kind, feats, tr, te)
                r = report("", te, s, thr)
                for k in tot:
                    tot[k] += r[k]
                for g, v in r["by_class"].items():
                    p, n = map(int, v.split("/"))
                    c = by_tot.setdefault(g, [0, 0]); c[0] += p; c[1] += n
        rec = {"name": f"{kind}/{cname}", **tot, "by_class": {g: f"{p}/{n}" for g, (p, n) in by_tot.items()}}
        res["page_cv"].append(rec)
        print("页折", rec["name"], {k: tot[k] for k in tot}, rec["by_class"])
        # 块折：每册内按页号切 5 连续块，整块留出
        d["_blk"] = d.groupby("book").page.transform(lambda p: pd.qcut(p.rank(method="first"), 5, labels=False))
        tot = {"body_FP": 0, "body_n": 0, "nonbody_TP": 0, "nonbody_n": 0}
        by_tot = {}
        for b in range(5):
            te = np.where(d._blk.values == b)[0]; tr = np.where(d._blk.values != b)[0]
            thr = threshold(kind, feats, tr)
            _, s = fit_score(kind, feats, tr, te)
            r = report("", te, s, thr)
            for k in tot:
                tot[k] += r[k]
            for g, v in r["by_class"].items():
                p, n = map(int, v.split("/"))
                c = by_tot.setdefault(g, [0, 0]); c[0] += p; c[1] += n
        rec = {"name": f"{kind}/{cname}", **tot, "by_class": {g: f"{p}/{n}" for g, (p, n) in by_tot.items()}}
        res["block_cv"].append(rec)
        print("块折", rec["name"], {k: tot[k] for k in tot}, rec["by_class"])
if a.json_out:
    open(a.json_out, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
