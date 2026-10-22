"""通用 IDS 判法（M7 IDS 通用计算第二步，2026-10-22）：计划 → 切 → 取判别叶子 → 最近邻 → 给字。

不再逐组手填切向、看哪一段、窗口：
1. **计划**（`ids_plan.derive_plan`）：由成员 IDS（字表 ids_lv1，组里 `ids_fine.tsv` 可给更细的写法）导出切向、判别那一段、判别叶子的路径；
2. **切**：缺省「形状先验折线」——建库时取该组人标切线的平均形状，线上在它附近（±`BAND`）用 DP 找穿墨最少的折线，不用训练；
   组里登记了 U-Net 权重（`unet`）就改用 U-Net 切（按册留出比先验折线好才登记，如 絕絶）；
3. **取叶子**：判别叶子在更深一层时（絕絶 判别在右部「色」的上半），先切出那一段、裁到墨迹外框，按子结构符自动缝第二刀取叶子；
4. **认**：叶子归一 32×32，与各字同一叶子的模板（真实刻例，**用同一切法切出**）比模糊 Dice 最近邻；margin 不够、某字模板不足都弃权。

为什么模板也用同一切法切（不用人标线）：按册留出实测，模板用人标线、测试格用机器线时，切口不一致使最近邻认错；
两边同一切法后 叙敘 0 错覆盖率 57%→100%（见 doc/design/M7-IDS通用计算.md 第四节）。这样没标切线的人裁格也都能进模板。

模板库沿用 `ids_online` 的格式（`templates={字: [32×32 uint8,…]}`），另存 `generic={"shape": [...], "frame": …, "path": …}`。
分层 L2：只依赖 numpy、PIL 与同包模块；torch 只在 U-Net 训练时用（`ids_unet`）。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from .ids_parts import norm_part, similarity
from .ids_plan import ORIENT, Plan, derive_plan, diff_leaves
from .ids_segment import ink_of
from .ids_two import auto_cut, cut_mask

#: 先验形状的采样点数、DP 搜索带宽（占图高／宽）、偏离先验的罚、步变罚
N_SHAPE = 64
BAND = 0.12
PULL = 3.0
LAM = 0.6
#: 第二刀（取深层叶子）在段内的先验位置
SUB_PRIOR = 0.45

_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=32)
def plan_of(members: str, group_dir: str) -> Plan:
    """成员串（排序后）→ 计划；按组目录缓存。"""
    return derive_plan(members, Path(group_dir))


def mean_shape(cuts, orient: str) -> list[float]:
    """人标折线 → N_SHAPE 个采样点上的平均位置（h：各 x 处的 y；v：各 y 处的 x），都是占图的比例。"""
    t = (np.arange(N_SHAPE) + 0.5) / N_SHAPE
    rows = []
    for cut in cuts:
        pts = sorted((q[0], q[1]) if orient == "h" else (q[1], q[0]) for q in cut)
        rows.append(np.interp(t, [a for a, _ in pts], [b for _, b in pts]))
    return [round(float(v), 4) for v in np.mean(rows, axis=0)]


def prior_seam(gray: np.ndarray, shape, orient: str, band: float = BAND, lam: float = LAM, pull: float = PULL, step: int = 4):
    """以平均形状为先验的 DP 缝 → 归一化折线（h 点自左向右，v 点自上而下）；无墨迹 → None。"""
    ink = ink_of(gray)
    if not ink.any():
        return None
    if orient == "v":
        ink = ink.T
    h, w = ink.shape
    prior = np.interp((np.arange(w) + 0.5) / w, (np.arange(len(shape)) + 0.5) / len(shape), np.asarray(shape)) * h
    ys = np.arange(h)[:, None]
    dist = np.abs(ys - prior[None, :])
    cost = ink.astype(float) + pull * dist / h
    cost[dist > band * h] = np.inf
    acc = np.full((h, w), np.inf)
    back = np.zeros((h, w), dtype=np.int16)
    acc[:, 0] = cost[:, 0]
    for x in range(1, w):
        prev = acc[:, x - 1]
        cand = np.stack([np.r_[np.inf, prev[:-1]] + lam, prev, np.r_[prev[1:], np.inf] + lam])
        k = cand.argmin(axis=0)
        acc[:, x] = cand[k, np.arange(h)] + cost[:, x]
        back[:, x] = k - 1
    i = int(acc[:, -1].argmin())
    path = [0] * w
    for x in range(w - 1, -1, -1):
        path[x] = i
        if x:
            i = min(max(i + int(back[i, x]), 0), h - 1)
    xs = list(range(0, w, step)) + [w - 1]
    pl = [[(x + 0.5) / w, (path[x] + 0.5) / h] for x in xs]
    return pl if orient == "h" else [[b, a] for a, b in pl]


def leaf_of(plan: Plan, gray: np.ndarray, polyline) -> np.ndarray | None:
    """切线分出判别那一段；判别叶子更深时再切一刀取叶子 → 归一 32×32 墨迹图（无墨迹 → None）。"""
    orient, which = plan.orient, plan.diff[0]
    m = cut_mask(gray.shape, polyline, orient)
    part = np.full_like(gray, 255)
    part[m == which] = gray[m == which]
    path = diff_leaves(plan)[0][0]
    sub = plan.root.sub[which]
    if len(path) < 2 or ORIENT.get(sub.idc) is None:
        return norm_part(part)
    ink = ink_of(part)
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    crop = part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    so = ORIENT[sub.idc]
    c2 = auto_cut(crop, so, SUB_PRIOR)
    if c2 is None:
        return None
    m2 = cut_mask(crop.shape, c2, so)
    q = np.full_like(crop, 255)
    q[m2 == path[1]] = crop[m2 == path[1]]
    return norm_part(q)


def usable(plan: Plan) -> bool:
    """通用判法只接「一刀两段、一个判别位置」的计划（叙敘、教敎、絕絶 等）；三段（彝）、整字（啓啟）另走。"""
    return plan.mode == "split" and plan.arity == 2 and len(plan.diff) == 1


def cut(plan: Plan, gray: np.ndarray, shape, net=None):
    """按计划切一刀：给了 U-Net（`ids_unet.NpNet`）用它，否则形状先验折线。"""
    if net is not None:
        from .ids_unet import predict_prob_np, prob_to_polyline2
        if not ink_of(gray).any():
            return None
        return prob_to_polyline2(predict_prob_np(net, gray), plan.orient)
    return prior_seam(gray, shape, plan.orient)


def choose(x: np.ndarray, templates: dict) -> tuple:
    """最近邻：→ (第一名字, margin, {字: 分})；不足两类 → (None, 0, {})。"""
    scores = {k: max(similarity(x, t) for t in ts) for k, ts in templates.items() if ts}
    if len(scores) < 2:
        return None, 0.0, scores
    r = sorted(scores.items(), key=lambda kv: -kv[1])
    return r[0][0], float(r[0][1] - r[1][1]), scores
