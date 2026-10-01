"""近形决胜：首选与次优异字 cov 差不足时，用**本库人裁刻例**自动求差异区域再局部比对
（2026-10-01，M5 道；方法与实测见 HANDOFF_M5.md）。

为什么需要：5a 的 `consensus_same` 要求首选比次优异字高 ≥0.03。形近对（𫎇/蒙、大/太、
論/諭、日/目…）在**整字** cov 上永远挤在一起（g3g4_error_analysis 核心负结果：全局相似度
下形近对与同字对分布重合），于是每次都「拿不准」、每次都送人。差别只在一小块（𫎇 的「业」头
vs 蒙 的「艹」头），整字 cov 把这块的信号摊薄在 64×64 里了。

为什么不再用字体两两对齐求差异框（match.py「按形区分四对」记的负结果）：两张**单例**图弹性
对齐后，笔粗/微小错位处处留残差，残差铺满画布，求不出紧凑的框。这里换成**两组**：

1. 每个字取库里最像查询的至多 `max_exemplars` 条**人裁**刻例（机器 align/match 进库的不算——
   实测四庫库里 8 条「蒙」有 5 条是 align/match 进的「𫎇」形，拿它们当原型等于把对手混进来）；
2. 高斯模糊（σ=`sigma`）+ 各自 ±`align` px 平移对齐到两组均值的中点；
3. 逐像素 Fisher 比 `(μA−μB)² / (合并方差+λ)`：笔粗与错位在组内方差里，被分母压掉；
   只有两组**系统性**不同的像素分子大、分母小。取前 `top` 比例的像素当差异区域 W；
4. 查询对两组均值在 W 上的加权距离：`s = (d_B − d_A) / Σ W(μA−μB)²`，
   查询等于 μA 时 s=+1、等于 μB 时 s=−1、正中间 0；
5. **库内自检**：同一流程对两组刻例逐条留一，算留一正确率 `loo_acc`。这一对在本库里本身
   分不开（留一错多）就弃权——安全靠这条把每一对按自己的数据标定，不用全局阈值。

放行条件（任一不满足 → 不改判，原样「拿不准」）：首选 cov ≥ `cov_min`；第三个异字比首选
低 ≥ `margin`（只在两字之间决胜）；两字各有 ≥ `min_exemplars` 条人裁刻例；`loo_acc ≥ loo_min`；
`|s| ≥ tau`。默认值是四庫库 423 个触发样本（人裁刻例按页分组留一）上标的，见 HANDOFF_M5.md。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class NearShapeConfig:
    margin: float = 0.03          # 触发：首选与次优异字 cov 差 < margin（与 consensus_margin 同口径）
    cov_min: float = 0.97         # 首选 cov 下限：整字都不太像时不在两字间硬选
    min_exemplars: int = 3        # 两字各至少几条人裁刻例
    max_exemplars: int = 40       # 每字最多取几条（按特征相似度取最像查询的）
    sigma: float = 1.5            # 模糊 σ（px，64 归一图）
    lam: float = 0.05             # Fisher 比分母的方差先验
    top: float = 0.12             # 差异区域取 Fisher 比前多少比例的像素
    align: int = 2                # 平移对齐半径（px）
    tau: float = 0.8              # |s| 放行门槛
    loo_min: float = 0.9          # 库内留一正确率门槛
    fit_q: float = 0.9            # 离群闸：拿胜者组留一距离的哪个分位数当尺子
    fit_max: float = 1.0          # 离群闸：查询距离 / 尺子 超过它就弃权
    flip_margin: float = 0.01     # 推翻 cov 排序（判次优胜）只在两者 cov 差 < 它时允许
    allow_guarded: bool = False   # 匹配器已判护栏（never_match/conflict）的格也许升档

    @classmethod
    def from_any(cls, v) -> "NearShapeConfig | None":
        """yaml 写法：`near_shape: true` / `{}` / `{tau: 0.9}` → 开；`false`/缺省 → 关。"""
        if v is None or v is False:
            return None
        if v is True:
            return cls()
        if isinstance(v, cls):
            return v
        return cls(**dict(v))


@dataclass
class NearShapeDecision:
    pair: tuple[str, str]               # (原首选, 原次优异字)
    winner: str | None                  # 决出的字；None = 弃权
    reason: str                         # decided | few_exemplars | cov_low | third_close | loo | low_score | outlier | flip_blocked
    score: float | None = None          # s，>0 偏向 pair[0]
    loo_acc: float | None = None
    n: tuple[int, int] = (0, 0)
    region_bbox: tuple[int, int, int, int] | None = None   # 差异区域外接框 (y0, y1, x0, x1)
    region_frac: float | None = None    # 差异区域权重落在外接框里的占比（紧凑度）
    fit: float | None = None            # 离群比：查询到胜者原型距离 / 胜者组留一距离 fit_q 分位

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("score", "loo_acc", "region_frac", "fit"):
            if d[k] is not None:
                d[k] = round(float(d[k]), 3)
        d["pair"] = list(self.pair)
        d["n"] = list(self.n)
        d["region_bbox"] = list(self.region_bbox) if self.region_bbox else None
        return d


def _prep(p: np.ndarray, sigma: float) -> np.ndarray:
    x = p.astype(np.float32)
    return cv2.GaussianBlur(x, (0, 0), sigma) if sigma > 0 else x


def _shift_to(x: np.ndarray, ref: np.ndarray, r: int) -> np.ndarray:
    """±r px 整数平移里取与 ref 相关最大的那个（np.roll，模糊后边缘近零，回卷无害）。"""
    if r <= 0:
        return x
    best, best_v = x, -1.0
    for dy in range(-r, r + 1):
        xs = np.roll(x, dy, 0)
        for dx in range(-r, r + 1):
            s = np.roll(xs, dx, 1)
            v = float((s * ref).sum())
            if v > best_v:
                best, best_v = s, v
    return best


def _stats(A: list[np.ndarray], B: list[np.ndarray], lam: float):
    A_, B_ = np.asarray(A), np.asarray(B)
    ma, mb = A_.mean(0), B_.mean(0)
    dof = max(len(A) + len(B) - 2, 1)
    var = (((A_ - ma) ** 2).sum(0) + ((B_ - mb) ** 2).sum(0)) / dof + lam
    return ma, mb, (ma - mb) ** 2 / var


def _region(fisher: np.ndarray, top: float) -> np.ndarray:
    fs = cv2.GaussianBlur(fisher, (0, 0), 1.0)
    thr = np.quantile(fs, 1 - top)
    return np.where(fs >= thr, fs, 0.0)


def _score(q: np.ndarray, ma: np.ndarray, mb: np.ndarray, w: np.ndarray) -> float:
    da = float((w * (q - ma) ** 2).sum())
    db = float((w * (q - mb) ** 2).sum())
    return (db - da) / (float((w * (ma - mb) ** 2).sum()) + 1e-9)


def _fit_score(q, A, B, cfg: NearShapeConfig):
    ma, mb, fisher = _stats(A, B, cfg.lam)
    w = _region(fisher, cfg.top)
    return _score(q, ma, mb, w), w, ma, mb


def _wdist(q, m, w) -> float:
    """差异区域内到原型的加权距离，按区域总权重归一。"""
    return float((w * (q - m) ** 2).sum() / (w.sum() + 1e-9))


def diff_map(A: list[np.ndarray], B: list[np.ndarray], cfg: NearShapeConfig = NearShapeConfig()):
    """两组刻例 → (μA, μB, Fisher 比, 差异区域 W)；可视化与证据用。"""
    Ap = [_prep(a, cfg.sigma) for a in A]
    Bp = [_prep(b, cfg.sigma) for b in B]
    c = (np.mean(Ap, 0) + np.mean(Bp, 0)) / 2
    Ap = [_shift_to(a, c, cfg.align) for a in Ap]
    Bp = [_shift_to(b, c, cfg.align) for b in Bp]
    ma, mb, fisher = _stats(Ap, Bp, cfg.lam)
    return ma, mb, fisher, _region(fisher, cfg.top)


def decide_pair(query: np.ndarray, A: list[np.ndarray], B: list[np.ndarray],
                cfg: NearShapeConfig = NearShapeConfig(),
                pair: tuple[str, str] = ("A", "B")) -> NearShapeDecision:
    """查询图在 A（pair[0]）与 B（pair[1]）两组刻例之间决胜。只看图，不看 cov。"""
    n = (len(A), len(B))
    if min(n) < cfg.min_exemplars:
        return NearShapeDecision(pair, None, "few_exemplars", n=n)
    Ap = [_prep(a, cfg.sigma) for a in A]
    Bp = [_prep(b, cfg.sigma) for b in B]
    c = (np.mean(Ap, 0) + np.mean(Bp, 0)) / 2
    Ap = [_shift_to(a, c, cfg.align) for a in Ap]
    Bp = [_shift_to(b, c, cfg.align) for b in Bp]
    q = _shift_to(_prep(query, cfg.sigma), c, cfg.align)
    s, w, ma, mb = _fit_score(q, Ap, Bp, cfg)
    hits = 0
    own = ([], [])          # 留一时每条刻例到**自己那组**原型的区域距离
    for i in range(len(Ap)):
        si, wi, mai, _ = _fit_score(Ap[i], Ap[:i] + Ap[i + 1:], Bp, cfg)
        hits += si > 0
        own[0].append(_wdist(Ap[i], mai, wi))
    for i in range(len(Bp)):
        si, wi, _, mbi = _fit_score(Bp[i], Ap, Bp[:i] + Bp[i + 1:], cfg)
        hits += si < 0
        own[1].append(_wdist(Bp[i], mbi, wi))
    loo = hits / (len(Ap) + len(Bp))
    # 离群闸：查询到胜者原型的距离 / 胜者组留一距离的 `fit_q` 分位数。>1 = 比胜者自己
    # 九成刻例都更不像胜者——多半是第三个字（真字根本不在这一对里）或残损，不该在两字里硬选。
    k = 0 if s > 0 else 1
    ref = float(np.quantile(own[k], cfg.fit_q))
    fit = _wdist(q, (ma, mb)[k], w) / (ref + 1e-9)
    ys, xs = np.nonzero(w)
    bbox = (int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1) if len(ys) else None
    frac = None
    if bbox is not None:
        frac = float(w[bbox[0]:bbox[1], bbox[2]:bbox[3]].sum() / (w.sum() + 1e-9))
    if loo < cfg.loo_min:
        reason, winner = "loo", None
    elif abs(s) < cfg.tau:
        reason, winner = "low_score", None
    elif fit > cfg.fit_max:
        reason, winner = "outlier", None
    else:
        reason, winner = "decided", (pair[0] if s > 0 else pair[1])
    return NearShapeDecision(pair, winner, reason, s, loo, n, bbox, frac, fit)


def trigger_pair(candidates, cfg: NearShapeConfig) -> tuple[tuple[str, str] | None, str | None]:
    """候选表 → 要决胜的字对；不触发返回 (None, None)，触发但不合格返回 (pair, 弃权理由)。"""
    if not candidates:
        return None, None
    top, ct = candidates[0]
    nxt = next(((c, v) for c, v in candidates[1:] if c != top), None)
    if nxt is None or ct - nxt[1] >= cfg.margin:
        return None, None
    pair = (top, nxt[0])
    if ct < cfg.cov_min:
        return pair, "cov_low"
    if any(v >= ct - cfg.margin for c, v in candidates if c not in pair):
        return pair, "third_close"
    return pair, None
