"""形近护栏格的书级刻形近邻判法（near_knn，全唐文 995ejelvk0，形近字线，2026-11-04）。

形近护栏（库首位与整理本两字相冲 conflict／never_match、或候选里有形近家族字 near_form）拦下的格，多数是
借来的殿本字形库认错：全唐文刻 未 被库排成 永、刻 四 被排成 内、刻 久 被排成 人／文……本书刻得清楚，
**用本书已放行格当刻例**（全书每字至多几十格），整字 HOG（同 `rr_shape`）投到 PCA 空间做近邻：

- **候选只在本格字、整理本对位字、库首位之间**（不引入第三个字）：只在候选字的刻例里取 k 近邻，
  同字票 ≥ `votes_min`、该字最近一格距离 < `ratio_max` × 别的候选字最近一格距离；
- **全书刻例库也得同意**：不限候选、在整个库里取 k 近邻，多数字必须就是这个字、票 ≥ `full_votes_min`
  （真字是第三个字时——比如候选 太/末 而刻的是 未——全库近邻会投给第三个字，弃权）；
- 离全库最近 5 格的平均距离 > `guard` → 字块怪（切坏、组外），弃权；
- `skip_chars`（全唐文：己已巳，原则上不靠字形）与 `skip_groups`（刻形分不开的组：大太、王玉、兩雨…）不判。

模型是书级数据（中心库数据目录 `config/groups/near_knn.json`，`schema: near_knn/1`；数组用 float16 base64 存），
由 `research/char_groups/near_knn_train.py` 从产物训练（按册留出定门槛）；没有这个文件的书本解法不出现，行为不变。
纯 numpy＋cv2，结果确定。
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

SCHEMA = "near_knn/1"


def pack(a: np.ndarray) -> dict:
    a = np.ascontiguousarray(a, np.float16)
    return {"shape": list(a.shape), "f16": base64.b64encode(a.tobytes()).decode("ascii")}


def unpack(d) -> np.ndarray:
    if isinstance(d, dict):
        return np.frombuffer(base64.b64decode(d["f16"]), np.float16).reshape(d["shape"]).astype(np.float32)
    return np.asarray(d, np.float32)


@lru_cache(maxsize=4)
def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"near_knn：{path} 不是 {SCHEMA}")
    for k in ("pca_mean", "pca", "bank"):
        d[k] = unpack(d[k])
    d["labels"] = np.asarray(d["labels"])
    d["skip_chars"] = frozenset(d.get("skip_chars") or ())
    d["skip_groups"] = frozenset(d.get("skip_groups") or ())
    d["_by"] = {c: np.where(d["labels"] == c)[0] for c in set(d["labels"].tolist())}
    return d


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def judge_feat(f: np.ndarray | None, model: dict, cands, exclude: np.ndarray | None = None) -> dict:
    """HOG 特征＋候选字 → {"char": 字|None, "why": …, 量}。`exclude`：训练留出时屏蔽的库格（布尔掩码）。"""
    if f is None:
        return {"char": None, "why": "abstain:no_ink"}
    by = model["_by"]
    cs = [c for c in dict.fromkeys(cands) if c and c in by and len(by[c]) >= model.get("min_n", 5)]
    if len(cs) < 2:
        return {"char": None, "why": "abstain:few_cands"}
    z = (np.asarray(f, np.float32) - model["pca_mean"]) @ model["pca"].T
    d = np.sqrt(((model["bank"] - z) ** 2).sum(1))
    if exclude is not None:
        d = np.where(exclude, np.inf, d)
    if not np.all(np.isfinite(d[~exclude] if exclude is not None else d)):
        return {"char": None, "why": "abstain:nan"}
    lab, k = model["labels"], model["k"]
    idx = np.concatenate([by[c] for c in cs])
    idx = idx[np.isfinite(d[idx])]
    li = lab[idx]
    if len(set(li.tolist())) < 2:
        return {"char": None, "why": "abstain:few_cands"}
    di = d[idx]
    o = np.argsort(di, kind="stable")[:k]
    top, votes = Counter(li[o].tolist()).most_common(1)[0]
    ratio = float(di[li == top].min() / di[li != top].min()) if di[li != top].min() > 0 else 0.0
    of = np.argsort(d, kind="stable")[:k]
    full, fvotes = Counter(lab[of].tolist()).most_common(1)[0]
    nn = float(d[of[:5]].mean())
    out = {"pick": top, "votes": int(votes), "ratio": round(ratio, 3), "full": full, "full_votes": int(fvotes),
           "nn": round(nn, 3), "cands": cs}
    if nn > model["guard"]:
        return {**out, "char": None, "why": "abstain:out_of_book"}
    if votes < model["votes_min"] or ratio >= model["ratio_max"]:
        return {**out, "char": None, "why": "abstain:low_margin"}
    if full != top or fvotes < model["full_votes_min"]:
        return {**out, "char": None, "why": "abstain:full_dissent"}
    return {**out, "char": top, "why": "agree"}


def judge(gray: np.ndarray, model: dict, cands) -> dict:
    from .rr_shape import features
    return judge_feat(features(gray)[0], model, cands)
