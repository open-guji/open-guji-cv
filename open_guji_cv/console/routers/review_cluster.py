# -*- coding: utf-8 -*-
"""批审组内按形聚簇：每簇只显示一张代表图（overview #166，2026-09-28）。

用户在服务器控制台做全唐文按字种批审时嫌图太多、加载太慢：「先对图片做聚类，
同一类显示一个就行了」。这里把一组（`group=char` 的一个字种、`group=shape` 的
一簇）里的待审格按 r5 embedding 余弦再聚成若干小簇，前端每簇只画代表图、旁标
「×N」，点开才加载成员；确认代表图 = 确认整簇（前端展开成 N 条 confirm 事件，
`via: cluster:<簇 id>`，可单独剔掉某一格）。

## 算法（纯函数，不碰 IO / 模型）

带密度序的领袖聚类（leader clustering），确定性、O(n²)：

1. 两两余弦矩阵 `S = E Eᵀ`；只有**键相同**（见下）的两格才算邻居；
2. 每格的邻居数 = 键相同且 `S ≥ thr` 的格数；按邻居数降序（同数按原顺序）挑种子；
3. 种子把尚未入簇、键相同、与它余弦 ≥ `thr` 的格全收进来；
4. 代表图 = 簇内离簇心（成员均值单位化）最近的那一格。

**键**＝格的「首选字」（`_top_pick`，借库书即 CNN 原型首选）加上人裁字（卡片上
若带了 `human`）。issue #166 CV 总管补充：「簇内有任意一格人裁或首选与代表图
不一致的，**不合进该簇**」——键不同的格从一开始就不算邻居，不会被收进去，因此
每一簇里的键都等于代表图的键。`group=char` 一组本来就同一个首选字，键只在
`group=shape`（形近对池化后一组里有几个首选字）时真起作用。

缺 embedding 的格（字块图算不出、CNN 不可用）各自单成一簇，不丢、不瞎并。

## 阈值（2026-09-28 标定，#166）

标定集：全唐文人裁 3866 格（qtw-draft `feedback/events/qtw-human-batch{1,2,3,5}`，
3807 格带字、59 格「看不清」；v006–v010 五册）。字块按线上同一口径取
（`borrow_first._card_patch` → r5 embedding），首选字用**只借四庫库**的 CNN 原型
（本书库里就有这批人裁刻例，拿它当首选等于泄题；只借库首选更差，标定偏保守）。
按首选字分组（与批审同一刀）、组内 `leader_cluster`，量「随代表图一起被确认的格里
人裁字 ≠ 代表图人裁字」（`calibrate()`）：

| thr | 屏上图数 | 错并/随代表确认 | 错率 | Wilson 95% 上界 | 单册最高 |
|---|---|---|---|---|---|
| 0.90 | 130 | 24/3736 | 0.64% | — | 1.21%（v006，超线） |
| 0.92 | 131 | 17/3735 | 0.46% | 0.73% | 0.54% |
| 0.93 | 132 | 11/3734 | 0.29% | 0.53% | 0.41% |
| 0.94 | 141 | 8/3725 | 0.21% | 0.42% | 0.41% |
| **0.95** | **149** | **8/3717** | **0.22%** | **0.42%** | **0.41%** |
| 0.96 | 161 | 7/3705 | 0.19% | 0.39% | 0.41% |

取 0.95：比 0.93 多画 17 张图，换来与 0.94 同样的错数且留余量。剩下 8 例余弦全在
0.94–0.997（主/王 两例 0.99、「看不清」并进 二/表 的五例、之 并进「看不清」代表一例），
**门槛调不动**——r5 embedding 本身分不开，只能靠人点开 ×N 看。3866 格压成 149 张
代表图（缩 26 倍）。
"""
from __future__ import annotations

from typing import Callable, Hashable, Sequence

import numpy as np

CLUSTER_THR = 0.95
"""组内并簇的余弦门槛（r5 embedding，单位向量内积）。标定见模块头与 #166。"""

MAX_CLUSTER_N = 4000
"""一组超过这么多格就不聚（O(n²) 的余弦矩阵：4000² float32 ≈ 64 MB）。
超了整组每格单成一簇——等于不聚，不比改前差。"""


def leader_cluster(emb: np.ndarray | None, keys: Sequence[Hashable], thr: float = CLUSTER_THR,
                   valid: Sequence[bool] | None = None) -> list[list[int]]:
    """→ 簇列表，每簇是下标列表，**代表图在第 0 位**，其余按与代表图余弦降序。

    `emb`：(n, d) 单位向量（`None` 或 `valid[i]=False` 的格各自单成一簇）；
    `keys`：每格的必须一致键（首选字 + 人裁字），键不同的两格永远不同簇。
    簇按大小降序，同大小按代表图原下标升序（确定性，前端翻页不乱跳）。
    """
    n = len(keys)
    if n == 0:
        return []
    ok = np.ones(n, bool) if valid is None else np.asarray(valid, bool)
    if emb is None or n > MAX_CLUSTER_N:
        ok = np.zeros(n, bool)
    idx = np.flatnonzero(ok)
    clusters: list[list[int]] = [[int(i)] for i in np.flatnonzero(~ok)]
    if len(idx):
        E = np.asarray(emb, np.float32)[idx]
        S = E @ E.T
        kk = [keys[i] for i in idx]
        codes = {k: j for j, k in enumerate(dict.fromkeys(kk))}
        kc = np.array([codes[k] for k in kk])
        adj = (S >= thr) & (kc[:, None] == kc[None, :])
        deg = adj.sum(1)
        order = sorted(range(len(idx)), key=lambda i: (-int(deg[i]), i))
        taken = np.zeros(len(idx), bool)
        for s in order:
            if taken[s]:
                continue
            mem = np.flatnonzero(adj[s] & ~taken)
            taken[mem] = True
            c = E[mem].mean(0)
            c /= max(float(np.linalg.norm(c)), 1e-9)
            rep = int(mem[int(np.argmax(E[mem] @ c))])
            rest = sorted((int(m) for m in mem if m != rep), key=lambda m: (-float(S[rep, m]), m))
            clusters.append([int(idx[rep])] + [int(idx[m]) for m in rest])
    clusters.sort(key=lambda cl: (-len(cl), cl[0]))
    return clusters


def cluster_tiles(tiles: list[dict], emb_of: Callable[[dict], np.ndarray | None],
                  key_of: Callable[[dict], Hashable], thr: float = CLUSTER_THR) -> list[dict]:
    """一组卡片 → 簇（给前端的形状）。`emb_of(tile)` 给单位向量或 `None`。

    每簇 `{"id", "rep", "n", "members": [{"id","patch","page","sim"}...]}`：
    `rep` 是代表图那张卡的**完整**卡片 dict（前端照旧画它的证据），`members`
    只留提交与点开看图要的几个字段（含代表图自己，排第一），组里几百格时
    也不让响应体膨胀。`sim` = 与代表图的余弦（代表图自己 1.0，缺向量 None）。
    簇 id = 代表图的格 id——同一批产物、同一门槛下稳定，事件里的
    `via: cluster:<id>` 能对回是哪张代表图带着确认的。
    """
    vecs = [emb_of(t) for t in tiles]
    valid = [v is not None for v in vecs]
    d = next((v.shape[0] for v in vecs if v is not None), 1)
    E = np.stack([v if v is not None else np.zeros(d, np.float32) for v in vecs]) if tiles else None
    groups = leader_cluster(E if any(valid) else None, [key_of(t) for t in tiles], thr, valid)
    out = []
    for cl in groups:
        rep = tiles[cl[0]]
        mem = []
        for i in cl:
            t = tiles[i]
            sim = (round(float(E[cl[0]] @ E[i]), 4)
                   if (E is not None and valid[i] and valid[cl[0]]) else None)
            mem.append({"id": t["id"], "patch": t.get("patch"), "page": t.get("page"),
                        "sim": sim})
        out.append({"id": rep["id"], "rep": rep, "n": len(cl), "members": mem})
    return out


# ── 标定（纯函数；IO 驱动脚本见 #166 进度评论）────────────────────────────


def calibrate(emb: np.ndarray, human: Sequence[str], first: Sequence[str],
              thrs: Sequence[float]) -> list[dict]:
    """人裁标定集上扫门槛：按首选字分组（与批审同一刀）、组内 `leader_cluster`，
    量「随代表图一起被确认的格里，人裁字 ≠ 代表图人裁字」的比例。

    `human[i]`：人裁字（「看不清」等无字裁决传一个不会与任何字相等的标记，
    如 `"__damaged__"`——把它并进有字的簇就是错，计入错数）。
    `first[i]`：首选字（分组键；键里**不放**人裁字——线上待审格没有人裁，
    放进去等于作弊）。

    → 每档 `{thr, n, n_shown, n_via_rep, n_bad, bad_rate, n_bad_all, bad_rate_all}`：
    `n_shown` = 屏上要画的图数（簇数），`n_via_rep` = 靠代表图带着确认的格数
    （簇里除代表图外的成员），`bad_rate = n_bad / n_via_rep`；`bad_rate_all` 分母
    换成全部格（审计口径更宽松，只作对照）。
    """
    by: dict[str, list[int]] = {}
    for i, f in enumerate(first):
        by.setdefault(f, []).append(i)
    out = []
    for thr in thrs:
        n_shown = n_via = n_bad = 0
        for ids in by.values():
            cls = leader_cluster(emb[ids], [first[i] for i in ids], thr)
            n_shown += len(cls)
            for cl in cls:
                rh = human[ids[cl[0]]]
                for j in cl[1:]:
                    n_via += 1
                    n_bad += human[ids[j]] != rh
        n = len(first)
        out.append({"thr": thr, "n": n, "n_shown": n_shown, "n_via_rep": n_via,
                    "n_bad": n_bad, "bad_rate": round(n_bad / n_via, 5) if n_via else 0.0,
                    "bad_rate_all": round(n_bad / n, 5) if n else 0.0})
    return out
