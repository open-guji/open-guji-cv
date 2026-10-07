# -*- coding: utf-8 -*-
"""语料分类器：语料内部留出自检 + dev 上定阈值曲线（只看 dev；val/vol05 在冻结阈值后一次性报）。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import common, corpus_clf as cc

X, y = cc.corpus_windows()
print("语料窗口", len(y), {c: int((y == i).sum()) for i, c in enumerate(cc.FAM)})
# 语料内部 80/20 自检
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
rng = np.random.RandomState(0); idx = rng.permutation(len(y)); k = int(.8 * len(y))
vec = DictVectorizer(); M = vec.fit_transform([X[i] for i in idx[:k]])
clf = LogisticRegression(C=1.0, max_iter=2000).fit(M, y[idx[:k]])
acc = (clf.predict(vec.transform([X[i] for i in idx[k:]])) == y[idx[k:]]).mean()
print("语料内部留出准确率", round(acc, 4))
model = cc.train(cache=Path("/tmp/claude-0/jys_clf.pkl"))
items = common.strong(common.load_items())
dev = [x for x in items if x["book"] in common.DEV]
P = cc.predict_proba(model, dev)
for th in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98):
    pred = {x["id"]: (cc.FAM[int(p.argmax())] if p.max() >= th else None) for x, p in zip(dev, P)}
    print(th, common.fmt(common.metrics(dev, pred)))
