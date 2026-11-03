"""字组书级刻形近邻判法（book_knn，全唐文 995ejelvk0，A24 形近字线，2026-11-03）。

借来的殿本字形库在全唐文上认不准某些组：门族 men 里本书刻「閒」（Kanripo 也作 閒），库按殿本排成「間」；
「闕N字」的「闕」被排成 閑／閣／問。全唐文刻得清楚，**用本书已放行格当刻例**，整字 HOG（与 `rr_shape` 同一特征）
投到 PCA 空间做 k 近邻就分得开：

- **A 档**：k 个近邻里同字 ≥ `votes_min`，且该字最近一格的距离 < `ratio_max` × 别字最近一格的距离 → 给字，不看整理本；
- **B 档**：同字 ≥ `ref_votes_min`、距离比 < `ref_ratio_max`，**且整理本对位字就是这个字** → 给字（两证）；
- 离训练格最近 5 个的平均距离 > `guard` → 组外字，弃权。

模型是书级数据（中心库数据目录 `config/groups/book_knn/<组>.json`，`schema: book_knn/1`），由
`research/char_groups/book_knn_train.py` 训练导出（按册留出定门槛）；没有这个文件的组本解法不出现，行为不变。
纯 numpy＋cv2，结果确定。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

SCHEMA = "book_knn/1"


@lru_cache(maxsize=16)
def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"book_knn：{path} 不是 {SCHEMA}")
    for k in ("pca_mean", "pca", "bank"):
        d[k] = np.asarray(d[k], np.float32)
    d["labels"] = np.asarray(d["labels"])
    return d


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def judge_feat(f: np.ndarray | None, model: dict, ref: str | None = None) -> dict:
    """HOG 特征 → {"char": 字|None, "why": …, "tier": A|B|None, 量}。"""
    if f is None:
        return {"char": None, "why": "abstain:no_ink", "tier": None}
    z = (np.asarray(f, np.float32) - model["pca_mean"]) @ model["pca"].T
    d = np.sqrt(((model["bank"] - z) ** 2).sum(1))
    if not np.all(np.isfinite(d)):
        return {"char": None, "why": "abstain:nan", "tier": None}
    lab = model["labels"]
    o = np.argsort(d, kind="stable")
    nn = float(d[o[:5]].mean())
    top, votes = Counter(lab[o[:model["k"]]].tolist()).most_common(1)[0]
    other = d[lab != top]
    ratio = float(d[lab == top].min() / other.min()) if other.size and other.min() > 0 else 0.0
    out = {"pick": top, "votes": int(votes), "ratio": round(ratio, 3), "nn": round(nn, 3)}
    if nn > model["guard"]:
        return {**out, "char": None, "why": "abstain:out_of_group", "tier": None}
    if votes >= model["votes_min"] and ratio < model["ratio_max"]:
        return {**out, "char": top, "why": "agree", "tier": "A"}
    if ref == top and votes >= model["ref_votes_min"] and ratio < model["ref_ratio_max"]:
        return {**out, "char": top, "why": "agree_ref", "tier": "B"}
    return {**out, "char": None, "why": "abstain:low_margin", "tier": None}


def judge(gray: np.ndarray, model: dict, ref: str | None = None) -> dict:
    from .rr_shape import features
    return judge_feat(features(gray)[0], model, ref)
