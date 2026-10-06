# -*- coding: utf-8 -*-
"""外部语料训练的「己已巳」搭配分类器（overview#443）。

训练：cv corpus/external/daizhige_*（与《總目》无重叠）里每个己/已/巳的前后 3 字窗口，
特征 = 位置字 + 几个组合（l1l2、r1r2、l1r1）+ 窗口内字袋；多项逻辑回归。
注意：语料里 已/巳 本身也有刻写讹混，标签带噪；这里只拿它当「搭配先验」，不当真值。
用法：train() 得到 (vectorizer, model)；predict_proba(items) 对 items.jsonl 的格给 [己,已,巳] 概率。
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

CV = Path(__file__).resolve().parents[3]
CORPUS = [CV / "corpus/external/daizhige_ru_yi.txt", CV / "corpus/external/daizhige_zhaoling.txt"]
FAM = "己已巳"
W = 3
_clean = re.compile(r"[\s　]+")


def feats(left: str, right: str) -> dict:
    l = ("|" * W + left)[-W:][::-1]          # l[0] 紧邻
    r = (right + "|" * W)[:W]
    f = {}
    for i, c in enumerate(l):
        f[f"l{i+1}={c}"] = 1
        f[f"bag={c}"] = 1
    for i, c in enumerate(r):
        f[f"r{i+1}={c}"] = 1
        f[f"bag={c}"] = 1
    f[f"l12={l[:2]}"] = 1
    f[f"r12={r[:2]}"] = 1
    f[f"l1r1={l[0]}{r[0]}"] = 1
    f[f"l1r12={l[0]}{r[:2]}"] = 1
    f[f"l12r1={l[:2]}{r[0]}"] = 1
    return f


def corpus_windows():
    X, y = [], []
    for p in CORPUS:
        t = p.read_text(encoding="utf-8").replace("\r", "")
        t = re.sub(r"\n+", "|", t)           # 换行当断点
        for m in re.finditer("[己已巳]", t):
            i = m.start()
            X.append(feats(t[max(0, i - W):i], t[i + 1:i + 1 + W]))
            y.append(FAM.index(t[i]))
    return X, np.array(y)


def train(C: float = 1.0, cache: Path | None = None):
    if cache and cache.exists():
        return pickle.loads(cache.read_bytes())
    X, y = corpus_windows()
    vec = DictVectorizer()
    M = vec.fit_transform(X)
    clf = LogisticRegression(C=C, max_iter=2000)
    clf.fit(M, y)
    if cache:
        cache.write_bytes(pickle.dumps((vec, clf)))
    return vec, clf


def predict_proba(model, items: list[dict], n_ctx: int = W) -> np.ndarray:
    vec, clf = model
    X = [feats((x.get("left") or "")[-n_ctx:].replace("□", "|"), (x.get("right") or "")[:n_ctx].replace("□", "|")) for x in items]
    P = clf.predict_proba(vec.transform(X))
    out = np.zeros((len(items), 3))
    for j, c in enumerate(clf.classes_):
        out[:, c] = P[:, j]
    return out
