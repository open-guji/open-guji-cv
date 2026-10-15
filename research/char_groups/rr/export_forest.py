# -*- coding: utf-8 -*-
"""把 Z-rr 的 4 类随机森林（clf2.py 的训练口径）导出成 numpy 可推理的 npz（overview#437 入人八接线，Z-jys）。

训练口径同 clf2：正例＝弱标签（C 档，dev+pool，不含强真值、不含 vol04）的放行字∈人入八；负例＝放行字、整理本都不在组内的格（含外围格）归第 4 类「其他」；
RandomForest(300, min_samples_leaf=2, class_weight=balanced, random_state=0)。特征由 `open_guji_cv/utils/rr_clf.py` 现算（与 feat.py 逐位一致，测试钉住）。
输出：models/rr_clf/forest.npz（所有树拼成一维数组 + 每树根偏移）、meta.json（训练口径、阈值、数据量、sha）。
用法：export_forest.py <dataset>/char-groups/rr [out_dir]"""
import hashlib, json, sys, os
from pathlib import Path
import numpy as np
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.utils import rr_clf

DS = Path(sys.argv[1]); out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[3] / "models/rr_clf"
CLS = rr_clf.CLASSES            # 人入八
R = [json.loads(l) for l in open(DS / "items.jsonl", encoding="utf-8")]
cp = lambda r: DS / "crops" / f"{r['id'].replace(':', '_')}.png"
R = [r for r in R if r["split"] != "extra" and cp(r).exists()]
import cv2
F = {}
for r in R:
    g = cv2.imread(str(cp(r)), 0)
    f = rr_clf.features(g)
    if f is not None: F[r["id"]] = f
strong = lambda r: r["gold_tier"] in ("A_human", "B_vision") and r["gold"] in CLS
weak = lambda r: r["core"] and r["gold_tier"] == "C_weak" and r["char"] in CLS
TRAIN = {"vol02", "vol03", "vol05", "vol06", "vol07", "vol08", "vol09", "vol10"}
pos = [r for r in R if weak(r) and r["book"] in TRAIN and r["id"] in F and not strong(r)]
neg = [r for r in R if r["id"] in F and (r["char"] or "") not in CLS and ((r["ref"] or "") not in CLS or not r["core"])]
X = np.vstack([np.array([F[r["id"]] for r in pos]), np.array([F[r["id"]] for r in neg])])
y = [CLS.index(r["char"]) for r in pos] + [3] * len(neg)
m = RandomForestClassifier(300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1).fit(X, y)
rr_clf.export_forest(m, out / "forest.npz")
sha = hashlib.sha256((out / "forest.npz").read_bytes()).hexdigest()[:16]
(out / "meta.json").write_text(json.dumps({
    "doc": "入人八 4 类森林（人入八＋其他），overview#437/#442/Z-jys 接线", "classes": "人入八其他", "trees": 300,
    "train": {"pos": len(pos), "neg": len(neg), "books": sorted(TRAIN), "excludes": "强真值格、vol04"},
    "thresholds": {"p": 0.5, "release_p": 0.8}, "sha256_16": sha}, ensure_ascii=False, indent=1), encoding="utf-8")
print("pos", len(pos), "neg", len(neg), "sha", sha, "size", (out / "forest.npz").stat().st_size)
# 与 sklearn 对拍
P = m.predict_proba(X[:50]); Q = rr_clf.Forest.load(out / "forest.npz").proba(X[:50])
print("max|sklearn-numpy|", float(np.abs(P - Q).max()))
