# -*- coding: utf-8 -*-
"""留出字种的 embedding 检索评测。

口径：query 图 → embedding → 与每个留出字的模板向量（同字模板取均值）
算余弦 → 排名。**候选集只含留出字**（893 个类表外字种），
所以这是 893-way 的开放集检索，不是 4,654-way 分类——分类头对这些字
物理上无法输出（它们不在类表里），这正是 06 卡说的「类外 top-1 = 0」。
"""
from __future__ import annotations

import numpy as np


def _embed(net, dev, imgs, scale, bs=512):
    import torch
    import torch.nn.functional as F
    net.eval()
    outs = []
    with torch.no_grad():
        for i in range(0, len(imgs), bs):
            xb = torch.tensor(imgs[i:i + bs][:, None].astype(np.float32), device=dev)
            e, _, _ = net(xb)
            outs.append(F.normalize(e, dim=1).cpu().numpy())
    net.train()
    return np.concatenate(outs)


def retrieval_eval(net, dev, ev, scale=16.0, ks=(1, 5, 10),
                   distractors: dict | None = None) -> dict:
    """distractors 给了就把它的模板也放进候选集（同字表但非评测字），
    模拟下游真实字表规模。

    **候选集大小是这条曲线上最敏感的旋钮**（2026-09-17 实测）：
    同一个 r4 checkpoint，893 候选下类外 top-1 96.7%，
    而 04 卡在 11,692 字候选下只有 73.9%。报数字必须带候选集规模，
    否则两份结果没法比。
    """
    qe = _embed(net, dev, ev["q_imgs"], scale)
    te = _embed(net, dev, ev["t_imgs"], scale)
    t_chars = np.array(ev["t_chars"])
    cand = sorted(set(ev["t_chars"]))
    if distractors:
        de = _embed(net, dev, distractors["t_imgs"], scale)
        d_chars = np.array(distractors["t_chars"])
        extra = sorted(set(distractors["t_chars"]) - set(cand))
        te = np.concatenate([te, de])
        t_chars = np.concatenate([t_chars, d_chars])
        cand = cand + extra
    ci = {c: i for i, c in enumerate(cand)}
    # 同字模板取均值再归一（与生产 _emb_index 的 mean 模式一致）
    M = np.zeros((len(cand), te.shape[1]), np.float32)
    for c in cand:
        M[ci[c]] = te[t_chars == c].mean(0)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    sim = qe @ M.T                                   # (nq, ncand)
    order = np.argsort(-sim, axis=1)
    gold = np.array([ci[c] for c in ev["q_chars"]])
    res = {"n": len(gold), "n_cand": len(cand)}
    for k in ks:
        res[f"top{k}"] = float((order[:, :k] == gold[:, None]).any(1).mean())
    # gap = top1 − top2（variant_form 放行闸用的那个量）
    s = np.sort(sim, axis=1)
    res["gap_mean"] = float((s[:, -1] - s[:, -2]).mean())
    # 按 query 来源分档
    src = np.array(ev["q_src"])
    res["by_src"] = {}
    for sv in sorted(set(ev["q_src"])):
        m = src == sv
        res["by_src"][sv] = {
            "n": int(m.sum()),
            "top1": float((order[m][:, :1] == gold[m][:, None]).any(1).mean()),
            "top10": float((order[m][:, :10] == gold[m][:, None]).any(1).mean()),
        }
    return res
