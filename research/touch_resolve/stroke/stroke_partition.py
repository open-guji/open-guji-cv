# -*- coding: utf-8 -*-
"""粘连字对的「笔画级归属」原型（实验件，不进生产包）。

逐像素分类（U-Net v2 / 模板归属）的共同失败模式是**一笔长长伸进邻字区域**：分类器在穿越处把这一笔切断，
下半截给了邻字；连通体多数票对「同一连通体两边都占」不起作用。这里把决策单位从像素抬到笔画段：

    墨 → 骨架 → 按交叉点拆段 → 交叉点处把「方向 / 宽度连续」的两段接成链 → 链内按 U-Net 逐像素票汇总
      → 链的票如果明显分成两段且分界处是**颈**（宽度局部极小，两字端对端粘连的典型形态）就在颈处劈开
      → 段级归属回填像素（每个墨像素归最近骨架点所在段）。

接口：
    stroke_owner(win_gray, unet_owner_px, params=None) -> owner   (1=上字 2=下字，仅墨像素有值)
    stroke_partition(...) -> StrokeResult                        （含骨架 / 段 / 链 / 票，供调试画图）

`unet_owner_px`：与窗口同形的 uint8，1=上字票 2=下字票，0=弃权（背景或分类器认为是背景）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

INK_TH = 128

DEFAULT_PARAMS = dict(
    spur_len=4,          # 一端自由、长度 < spur_len 的骨架毛刺删掉（0 = 不剪）
    zone_r=1,            # 交叉点像素向外 zone_r 像素内的骨架都算交叉区（大了会把笔画头部的「疙瘩」整个吞成交叉区，其墨就被邻臂认走）
    bridge_len=3,        # 两端都接交叉区、长度 ≤ bridge_len 的段并进交叉区（Y-Y 短桥）
    dir_n=10,            # 估计臂方向用的骨架点数
    ang_max=30.0,        # 两臂接成链允许的偏离直线角（度）
    wr_min=0.5,          # 两臂宽度比下限（min/max）
    chain=True,          # 关掉 = 纯段级投票（消融）
    split_min_gain=15,   # 链内劈开至少要把错票减少这么多像素
    split_gain_frac=0.5, # 且减少量 ≥ base_cost 的这个比例
    neck_ratio=0.8,      # 颈：宽度 ≤ 链中位宽 × neck_ratio
    neck_rise=1.0,       # 且两侧 3–10 点内宽度都要比颈高出 ≥ neck_rise 像素
    neck_r=8,            # 在票分界点 ±neck_r 内找颈
    end_margin=3,        # 链的某端接着交叉区时，离该端 < end_margin 个点内不劈（免得劈出 1–2 个点的碎单元）
    interior_split=True, # 分界点在段内部（不在接链的交叉处）且无颈时，票差足够大也允许劈
    interior_gain=40,    # 上一条的票差门槛（像素）
    interior_frac=0.6,
    max_depth=2,
    core_rule="seed",    # 交叉核心像素：seed=归最近种子；vote=按 U-Net 逐像素票
    ext_len=3,           # 臂端沿自身方向向交叉区内延伸 ext_len 个「延伸种子」（只盖交叉核心本身），0 = 不延伸
)


# ───────────────────────── 数据结构 ─────────────────────────
@dataclass
class Segment:
    sid: int
    pts: np.ndarray                   # (n, 2) 有序 (y, x)
    zone_at: dict = field(default_factory=dict)   # end(0/1) -> zone id
    link: dict = field(default_factory=dict)      # end(0/1) -> (other_sid, other_end)

    @property
    def n(self) -> int:
        return int(self.pts.shape[0])


@dataclass
class StrokeResult:
    owner: np.ndarray                 # 最终归属
    skeleton: np.ndarray              # bool
    zone: np.ndarray                  # bool，交叉区骨架
    seed_label: np.ndarray            # int32，与窗口同形；每个骨架种子点所属「决策单元」编号（-1 无）
    unit_label: dict                  # 决策单元编号 -> 1/2
    segments: list                    # list[Segment]
    n_chains: int = 0
    n_splits: int = 0
    n_pairs: int = 0
    fallback_px: int = 0              # 没有骨架种子、退回逐像素票的墨像素数


# ───────────────────────── 骨架图 ─────────────────────────
_K8 = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.uint8)


def _degree(sk: np.ndarray) -> np.ndarray:
    nb = cv2.filter2D(sk.astype(np.uint8), -1, _K8, borderType=cv2.BORDER_CONSTANT)
    return nb * sk.astype(np.uint8)


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return m.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(m.astype(np.uint8), k).astype(bool)


def _order_points(mask: np.ndarray) -> np.ndarray:
    """一段骨架像素（bool 图，应是 8 连通细线）→ 有序 (y,x) 列表：从度最小的点 BFS。"""
    ys, xs = np.nonzero(mask)
    n = ys.size
    if n <= 2:
        return np.stack([ys, xs], 1)
    idx = {(int(y), int(x)): i for i, (y, x) in enumerate(zip(ys, xs))}
    nbrs = [[] for _ in range(n)]
    for (y, x), i in idx.items():
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    j = idx.get((y + dy, x + dx))
                    if j is not None:
                        nbrs[i].append(j)
    deg = np.array([len(v) for v in nbrs])
    start = int(np.argmin(deg + ys * 1e-6))       # 度最小；平手取最上面的
    seen = np.zeros(n, bool); order = []; q = [start]; seen[start] = True
    while q:
        i = q.pop(0); order.append(i)
        for j in nbrs[i]:
            if not seen[j]:
                seen[j] = True; q.append(j)
    # 不连通的残余（理论上没有）追加在后
    for i in range(n):
        if not seen[i]:
            order.append(i)
    return np.stack([ys[order], xs[order]], 1)


def _prune_spurs(sk: np.ndarray, spur_len: int, rounds: int = 3) -> np.ndarray:
    sk = sk.copy()
    for _ in range(rounds):
        deg = _degree(sk)
        J = deg >= 3
        if not J.any():
            break
        body = sk & ~J
        n, lab = cv2.connectedComponents(body.astype(np.uint8), connectivity=8)
        if n <= 1:
            break
        Jd = _dilate(J, 1)
        sizes = np.bincount(lab.ravel(), minlength=n)
        endpoint = deg == 1
        removed = False
        for i in range(1, n):
            if sizes[i] >= spur_len:
                continue
            m = lab == i
            if not (m & endpoint).any():          # 两端都接交叉：是桥，不是毛刺
                continue
            if not (m & Jd).any():                # 孤立小段：不是毛刺
                continue
            sk[m] = False; removed = True
        if not removed:
            break
    return sk


def _build_graph(sk: np.ndarray, p: dict) -> tuple[list[Segment], np.ndarray, np.ndarray]:
    """骨架 → (segments, zone_mask, zone_label)。"""
    deg = _degree(sk)
    J = deg >= 3
    zone = sk & _dilate(J, p["zone_r"]) if J.any() else np.zeros_like(sk)
    # 短桥并进交叉区（迭代两轮足够）
    for _ in range(2):
        body = sk & ~zone
        n, lab = cv2.connectedComponents(body.astype(np.uint8), connectivity=8)
        zd = _dilate(zone, 1)
        nz, zlab = cv2.connectedComponents(zone.astype(np.uint8), connectivity=8)
        changed = False
        for i in range(1, n):
            m = lab == i
            if int(m.sum()) > p["bridge_len"]:
                continue
            touch = np.unique(zlab[_dilate(m, 1) & zone])
            touch = touch[touch > 0]
            if touch.size >= 2 or (touch.size == 1 and not (m & (deg == 1)).any() and int(m.sum()) <= 2):
                zone[m] = True; changed = True
        if not changed:
            break
    body = sk & ~zone
    n, lab = cv2.connectedComponents(body.astype(np.uint8), connectivity=8)
    nz, zlab = cv2.connectedComponents(zone.astype(np.uint8), connectivity=8)
    segs: list[Segment] = []
    for i in range(1, n):
        m = lab == i
        pts = _order_points(m)
        seg = Segment(sid=len(segs), pts=pts)
        # 两端接哪个交叉区
        for end, pt in ((0, pts[0]), (1, pts[-1])):
            y, x = int(pt[0]), int(pt[1])
            y0, y1 = max(0, y - 1), min(sk.shape[0], y + 2); x0, x1 = max(0, x - 1), min(sk.shape[1], x + 2)
            zz = zlab[y0:y1, x0:x1]; zz = zz[zz > 0]
            if zz.size:
                seg.zone_at[end] = int(np.bincount(zz).argmax())
        # 单点 / 两点段：两端同一点，若接交叉只记一端
        if seg.n <= 2 and 0 in seg.zone_at and 1 in seg.zone_at and seg.zone_at[0] == seg.zone_at[1]:
            del seg.zone_at[1]
        segs.append(seg)
    return segs, zone, zlab


def _arm_dir(seg: Segment, end: int, n: int) -> np.ndarray | None:
    pts = seg.pts if end == 1 else seg.pts[::-1]     # 让 pts[-1] 是接交叉的那一端
    if pts.shape[0] < 3:
        return None
    k = min(n, pts.shape[0])
    tail = pts[-k:].astype(np.float64)
    v = tail[-1] - tail[0]
    if np.hypot(*v) < 1e-6:
        return None
    # 用 PCA 主方向稳一点，符号对齐到 v
    c = tail - tail.mean(0)
    if k >= 5:
        w, vec = np.linalg.eigh(c.T @ c)
        d = vec[:, int(np.argmax(w))]
        if d @ v < 0:
            d = -d
    else:
        d = v
    return d / np.hypot(*d)


def _arm_width(seg: Segment, end: int, dt: np.ndarray, n: int) -> float:
    pts = seg.pts if end == 1 else seg.pts[::-1]
    k = min(n, pts.shape[0])
    tail = pts[-k:]
    if k > 4:
        tail = tail[:-2]                                    # 最靠交叉的两点被交叉撑胖，不算
    return float(2.0 * dt[tail[:, 0], tail[:, 1]].mean())


def _pair_arms(segs: list[Segment], zlab: np.ndarray, dt: np.ndarray, p: dict) -> int:
    """每个交叉区里把最接近直线延伸、宽度相近的两臂接起来。返回接了几对。"""
    arms: dict[int, list] = {}
    for s in segs:
        for end, z in s.zone_at.items():
            d = _arm_dir(s, end, p["dir_n"])
            if d is None:
                continue
            arms.setdefault(z, []).append((s, end, d, _arm_width(s, end, dt, p["dir_n"])))
    n_pairs = 0
    for z, lst in arms.items():
        if len(lst) < 2:
            continue
        cands = []
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                sa, ea, da, wa = lst[i]; sb, eb, db, wb = lst[j]
                if sa.sid == sb.sid:
                    continue
                cosang = float(np.clip(-(da @ db), -1, 1))      # 直穿过去 = da 与 -db 同向
                dev = float(np.degrees(np.arccos(cosang)))
                wr = min(wa, wb) / max(wa, wb, 1e-6)
                if dev <= p["ang_max"] and wr >= p["wr_min"]:
                    cands.append((dev + 40.0 * (1 - wr), i, j))
        used = set()
        for _, i, j in sorted(cands):
            if i in used or j in used:
                continue
            sa, ea, _, _ = lst[i]; sb, eb, _, _ = lst[j]
            if ea in sa.link or eb in sb.link:
                continue
            sa.link[ea] = (sb.sid, eb); sb.link[eb] = (sa.sid, ea)
            used.add(i); used.add(j); n_pairs += 1
    return n_pairs


def _chains(segs: list[Segment]) -> list[list[tuple[int, bool]]]:
    """按 link 走成链：每条链是 [(sid, reversed?)...]，reversed 表示该段要倒着接。"""
    by_id = {s.sid: s for s in segs}
    seen = set(); chains = []

    def walk(start: Segment, enter_end: int):
        out = []; s = start; e = enter_end
        while True:
            seen.add(s.sid)
            out.append((s.sid, e == 1))           # 从 end 1 进入 → 倒序
            far = 1 - e
            nxt = s.link.get(far)
            if nxt is None or nxt[0] in seen:
                break
            s = by_id[nxt[0]]; e = nxt[1]
        return out

    for s in segs:
        if s.sid in seen:
            continue
        if 0 not in s.link:
            chains.append(walk(s, 0))
        elif 1 not in s.link:
            chains.append(walk(s, 1))
    for s in segs:                                 # 剩下的是环
        if s.sid not in seen:
            chains.append(walk(s, 0))
    return chains


# ───────────────────────── 投票与劈分 ─────────────────────────
def _is_neck(w: np.ndarray, j: int, med: float, p: dict) -> bool:
    n = w.size
    if w[j] > p["neck_ratio"] * med:
        return False
    lo = w[max(0, j - 10): j]
    hi = w[j + 1: min(n, j + 11)]
    if lo.size == 0 or hi.size == 0:
        return False
    return (lo.max() - w[j] >= p["neck_rise"]) and (hi.max() - w[j] >= p["neck_rise"])


def _decide(v1: np.ndarray, v2: np.ndarray, w: np.ndarray, seg_of: np.ndarray, near_end: np.ndarray, p: dict, depth: int,
            out: list, stats: dict) -> None:
    """一条有序链的票 → 追加 (slice_start, slice_end, label) 到 out（下标相对本链）。递归劈分。"""
    n = v1.size
    t1, t2 = int(v1.sum()), int(v2.sum())
    label = 1 if t1 > t2 else (2 if t2 > t1 else 0)
    base = min(t1, t2)
    if base < p["split_min_gain"] or n < 12 or depth >= p["max_depth"]:
        out.append((0, n, label)); return
    c1 = np.cumsum(v1); c2 = np.cumsum(v2)
    i = np.arange(6, n - 5)                        # split 在 i 之前 / 之后
    left1 = c1[i - 1]; left2 = c2[i - 1]
    costA = left2 + (t1 - left1)                   # 左=1 右=2
    costB = left1 + (t2 - left2)                   # 左=2 右=1
    cost = np.minimum(costA, costB)
    k = int(np.argmin(cost)); istar = int(i[k]); best = int(cost[k])
    gain = base - best
    if gain < p["split_min_gain"] or gain < p["split_gain_frac"] * base:
        out.append((0, n, label)); return
    med = float(np.median(w))
    lo, hi = max(1, istar - p["neck_r"]), min(n - 1, istar + p["neck_r"] + 1)
    j = lo + int(np.argmin(w[lo:hi]))
    split_at = None
    if near_end[j] or near_end[istar]:
        pass                                        # 贴着交叉区的假颈 / 假分界：整链一起投
    elif _is_neck(w, j, med, p):
        split_at = j; stats["neck"] = stats.get("neck", 0) + 1
    elif p["interior_split"]:
        # 分界点是否落在两段的接缝（交叉区）附近：是则是「穿越」，信连续性不劈
        near_junction = bool((seg_of[max(0, istar - 3): min(n, istar + 3)] != seg_of[istar]).any()) or \
            bool((seg_of[max(0, istar - 4): istar] != seg_of[istar - 1]).any())
        if not near_junction and gain >= p["interior_gain"] and gain >= p["interior_frac"] * base:
            split_at = istar; stats["interior"] = stats.get("interior", 0) + 1
    if split_at is None:
        out.append((0, n, label)); return
    stats["splits"] = stats.get("splits", 0) + 1
    sub = []
    _decide(v1[:split_at], v2[:split_at], w[:split_at], seg_of[:split_at], near_end[:split_at], p, depth + 1, sub, stats)
    out.extend(sub)
    sub = []
    _decide(v1[split_at:], v2[split_at:], w[split_at:], seg_of[split_at:], near_end[split_at:], p, depth + 1, sub, stats)
    out.extend([(a + split_at, b + split_at, l) for a, b, l in sub])


# ───────────────────────── 主流程 ─────────────────────────
def stroke_partition(win_gray: np.ndarray, unet_owner_px: np.ndarray, params: dict | None = None) -> StrokeResult:
    p = dict(DEFAULT_PARAMS); p.update(params or {})
    W = (win_gray < INK_TH)
    h, w = W.shape
    votes = unet_owner_px.astype(np.uint8) * W
    owner = np.zeros((h, w), np.uint8)
    seed_label = np.full((h, w), -1, np.int32)
    if not W.any():
        return StrokeResult(owner, np.zeros_like(W), np.zeros_like(W), seed_label, {}, [])
    dt = cv2.distanceTransform(W.astype(np.uint8), cv2.DIST_L2, 3).astype(np.float32)
    sk0 = skeletonize(W)
    sk = _prune_spurs(sk0, p["spur_len"]) if p["spur_len"] > 0 else sk0.copy()
    segs, zone, zlab = _build_graph(sk, p)
    n_pairs = _pair_arms(segs, zlab, dt, p) if p["chain"] else 0
    chains = _chains(segs)

    # 种子：段上的骨架点。seed_id 逐点编号，方便 bincount
    seed_pts = []; seed_seg = []
    for s in segs:
        seed_pts.append(s.pts); seed_seg.append(np.full(s.n, s.sid, np.int32))
    if not seed_pts:
        fb = np.where(votes == 0, 2, votes).astype(np.uint8) * W
        return StrokeResult(fb, sk, zone, seed_label, {}, segs, fallback_px=int(W.sum()))
    seed_pts = np.concatenate(seed_pts); seed_seg = np.concatenate(seed_seg)
    seed_index = np.full((h, w), -1, np.int32)
    seed_index[seed_pts[:, 0], seed_pts[:, 1]] = np.arange(seed_pts.shape[0])
    # 段内点的下标（有序），供链拼接
    seg_start = {}
    acc = 0
    for s in segs:
        seg_start[s.sid] = acc; acc += s.n

    # 臂端延伸种子：接着交叉区的段端，沿臂方向往交叉区里走 ≤ ext_len 个像素（只在墨内、不撞别的段的种子），
    # 这些像素当作该段端点的「替身」参与最近种子分配——让笔画在交叉处直穿，而不是把交叉核心让给离得近的另一臂。
    assign_index = seed_index.copy()
    n_ext = 0
    if p["ext_len"] > 0:
        for sg in segs:
            for end in sg.zone_at:
                d = _arm_dir(sg, end, p["dir_n"])
                if d is None:
                    continue
                e_pt = sg.pts[-1] if end == 1 else sg.pts[0]
                own_idx = seed_index[e_pt[0], e_pt[1]]
                for t in range(1, int(p["ext_len"]) + 1):
                    q = np.round(e_pt + t * d).astype(int)
                    if not (0 <= q[0] < h and 0 <= q[1] < w) or not W[q[0], q[1]]:
                        break
                    if seed_index[q[0], q[1]] >= 0 and seed_index[q[0], q[1]] != own_idx:
                        break
                    if assign_index[q[0], q[1]] < 0:
                        assign_index[q[0], q[1]] = own_idx; n_ext += 1

    # 墨像素 → 最近种子（段上的骨架点；按墨连通体分别做，不隔空认亲）。
    # 另记每个墨像素的最近**骨架点**是否落在交叉区 / 已剪毛刺上（core=交叉核心）：
    #   core_rule="seed"：核心像素也归最近种子；core_rule="vote"：核心像素按 U-Net 逐像素票（弃权跟最近种子）。
    assign = np.full((h, w), -1, np.int32)
    core_mask = np.zeros((h, w), bool)
    ncc, cl = cv2.connectedComponents(W.astype(np.uint8), connectivity=8)
    fallback_px = 0
    for c in range(1, ncc):
        m = cl == c
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        sub_m = m[y0:y1, x0:x1]; sub_seed = assign_index[y0:y1, x0:x1]
        has = (sub_seed >= 0) & sub_m
        if not has.any():
            fallback_px += int(sub_m.sum()); continue
        _, (iy, ix) = ndi.distance_transform_edt(~has, return_indices=True)
        lab = sub_seed[iy, ix]
        a = assign[y0:y1, x0:x1]
        a[sub_m] = lab[sub_m]
        if p["core_rule"] == "vote":
            sub_sk = sk0[y0:y1, x0:x1] & sub_m
            _, (jy, jx) = ndi.distance_transform_edt(~sub_sk, return_indices=True)
            near_seed = seed_index[y0:y1, x0:x1][jy, jx] >= 0
            cm = core_mask[y0:y1, x0:x1]
            cm[sub_m & ~near_seed] = True
    ink_y, ink_x = np.nonzero(W)
    a_ink = assign[ink_y, ink_x]; v_ink = votes[ink_y, ink_x]
    ok = a_ink >= 0
    nseed = seed_pts.shape[0]
    votes1 = np.bincount(a_ink[ok & (v_ink == 1)], minlength=nseed)
    votes2 = np.bincount(a_ink[ok & (v_ink == 2)], minlength=nseed)
    width = 2.0 * dt[seed_pts[:, 0], seed_pts[:, 1]]

    # 链 → 决策单元
    unit_label: dict[int, int] = {}
    unit_of_seed = np.full(nseed, -1, np.int32)
    stats: dict = {}
    uid = 0
    for ch in chains:
        idx = []
        seg_of = []
        for sid, rev in ch:
            s = segs[sid]
            r = np.arange(seg_start[sid], seg_start[sid] + s.n)
            if rev:
                r = r[::-1]
            idx.append(r); seg_of.append(np.full(s.n, sid, np.int32))
        idx = np.concatenate(idx); seg_of = np.concatenate(seg_of)
        near_end = np.zeros(idx.size, bool)
        sid0, rev0 = ch[0]; sid1, rev1 = ch[-1]
        if (1 if rev0 else 0) in segs[sid0].zone_at:
            near_end[: p["end_margin"]] = True
        if (0 if rev1 else 1) in segs[sid1].zone_at:
            near_end[max(0, idx.size - p["end_margin"]):] = True
        parts: list = []
        _decide(votes1[idx], votes2[idx], width[idx], seg_of, near_end, p, 0, parts, stats)
        for a, b, label in parts:
            unit_label[uid] = label; unit_of_seed[idx[a:b]] = uid; uid += 1
    # 无票单元（label 0）：跟最近的有票单元
    lab_seed = np.array([unit_label.get(int(u), 0) if u >= 0 else 0 for u in unit_of_seed], np.uint8)
    if (lab_seed == 0).any() and (lab_seed > 0).any():
        good = lab_seed > 0
        tree_pts = seed_pts[good]; tree_lab = lab_seed[good]
        for i in np.nonzero(~good)[0]:
            d = ((tree_pts - seed_pts[i]) ** 2).sum(1)
            lab_seed[i] = tree_lab[int(np.argmin(d))]
        for u in range(uid):
            if unit_label.get(u, 0) == 0:
                sel = unit_of_seed == u
                if sel.any():
                    unit_label[u] = int(np.bincount(lab_seed[sel]).argmax())
    # 回填
    own_ink = np.zeros(ink_y.size, np.uint8)
    own_ink[ok] = lab_seed[a_ink[ok]]
    # 交叉核心按票（core_rule="vote" 时才有）
    core = core_mask[ink_y, ink_x] & ok
    if core.any():
        cv = v_ink[core]
        own_ink[core] = np.where(cv > 0, cv, own_ink[core])
    # 没种子的墨（整个连通体无骨架：退回逐像素票，0→2 与 U-Net 评测同口径）
    fb = ~ok
    if fb.any():
        own_ink[fb] = np.where(v_ink[fb] == 0, 2, v_ink[fb])
    owner[ink_y, ink_x] = own_ink
    seed_label[seed_pts[:, 0], seed_pts[:, 1]] = unit_of_seed
    return StrokeResult(owner, sk, zone, seed_label, unit_label, segs, n_chains=len(chains),
                        n_splits=stats.get("splits", 0), n_pairs=n_pairs, fallback_px=fallback_px)


def stroke_owner(win_gray: np.ndarray, unet_owner_px: np.ndarray, params: dict | None = None) -> np.ndarray:
    """窗口灰度 + U-Net 逐像素票（1/2，0=弃权）→ 笔画级归属 owner（1=上字 2=下字，仅墨像素）。"""
    return stroke_partition(win_gray, unet_owner_px, params).owner


# ───────────────────────── 调试画图 ─────────────────────────
def draw_units(win_gray: np.ndarray, res: StrokeResult, scale: int = 3) -> np.ndarray:
    """墨淡灰，骨架按决策单元随机上色（红系=上字 蓝系=下字），交叉区画黄。"""
    h, w = win_gray.shape
    vis = np.full((h, w, 3), 255, np.uint8)
    vis[win_gray < INK_TH] = (200, 200, 200)
    vis = cv2.resize(vis, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
    rng = np.random.RandomState(0)
    colors = {}
    ys, xs = np.nonzero(res.seed_label >= 0)
    for y, x in zip(ys, xs):
        u = int(res.seed_label[y, x])
        if u not in colors:
            lab = res.unit_label.get(u, 0)
            base = np.array([0, 0, 200]) if lab == 1 else (np.array([200, 80, 0]) if lab == 2 else np.array([0, 160, 0]))
            jit = rng.randint(-60, 60, 3)
            colors[u] = tuple(int(v) for v in np.clip(base + jit, 0, 255))
        cv2.rectangle(vis, (x * scale, y * scale), (x * scale + scale - 1, y * scale + scale - 1), colors[u], -1)
    zy, zx = np.nonzero(res.zone)
    for y, x in zip(zy, zx):
        cv2.rectangle(vis, (x * scale, y * scale), (x * scale + scale - 1, y * scale + scale - 1), (0, 220, 255), -1)
    return vis
