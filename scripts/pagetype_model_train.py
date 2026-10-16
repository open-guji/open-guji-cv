# -*- coding: utf-8 -*-
"""训练页型「正文/非正文」闸模型（P1 道）。

输入：research/pagetype_model/extract.py 产的 features csv（page-type 金标页 × 信号）。
成员 = HGB(step1+col 两组信号)；门槛 = 训练集多种子折外（OOF）正文最高得分 + margin，
零容忍误判正文。写 models/pagetype/pagetype_v1.joblib(+json)。
用法：python scripts/pagetype_model_train.py --feats feats_all.csv [--holdout-feats ...]
"""
from __future__ import annotations

import argparse
import subprocess
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold

from open_guji_cv.pagetype_model import signals as S
from open_guji_cv.pagetype_model.model import DEFAULT_MODEL, save_model

warnings.filterwarnings("ignore")
FEATS = [f for f in S.FEATURES if S.GROUP_OF[f] in ("step1", "col")]


def mk():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08, max_iter=150,
                                          class_weight="balanced", random_state=0)


def oof_body_max(d, y, seeds=5):
    mx = 0.0
    for sd in range(seeds):
        for a, b in StratifiedKFold(5, shuffle=True, random_state=sd).split(d, d.gold):
            m = mk().fit(d.iloc[a][FEATS], y[a])
            s = m.predict_proba(d.iloc[b][FEATS])[:, 1]
            mx = max(mx, float(s[y[b] == 0].max()))
    return mx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feats", required=True)
    ap.add_argument("--holdout-feats", help="留出页 csv：只测，不进训练也不进门槛")
    ap.add_argument("--out", default=str(DEFAULT_MODEL))
    ap.add_argument("--margin", type=float, default=0.0)
    a = ap.parse_args()
    d = pd.read_csv(a.feats)
    d = d[d.gold != "uncertain"].reset_index(drop=True)
    y = (d.gold != "body").astype(int).values
    thr = min(1.0, oof_body_max(d, y) + a.margin)
    m = mk().fit(d[FEATS], y)
    if a.holdout_feats:
        h = pd.read_csv(a.holdout_feats)
        s = m.predict_proba(h[FEATS])[:, 1]
        print(f"留出 {len(h)} 页：门槛 {thr:.4f}，被判非正文 {(s > thr).sum()}，最高分 {s.max():.4f}")
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        rev = ""
    fp = save_model(a.out, [{"name": "hgb_step1_col", "clf": m, "features": FEATS, "thr": thr}], {
        "model_id": "pagetype_v1", "classifier": "HistGradientBoosting(depth3,lr.08,150it,balanced)",
        "calibration": "无；门槛=5种子×5折OOF正文最高分+margin", "margin": a.margin,
        "train_books": {b: int((d.book == b).sum()) for b in sorted(set(d.book))},
        "train_gold": {g: int((d.gold == g).sum()) for g in sorted(set(d.gold))},
        "n_pages": int(len(d)), "cv_commit": rev,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": "只判非正文（roster/toc 为主）；极少类 cover/label/blank 保留现行规则。见 research/pagetype_model/README.md"})
    print("thr", round(thr, 4), "fingerprint", fp, "->", a.out)


if __name__ == "__main__":
    main()
