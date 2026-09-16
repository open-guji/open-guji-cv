# -*- coding: utf-8 -*-
"""模板配准引擎：把「A 在上、B 在下」的两张模板贴到双格窗口上，给出贴合度与像素归属。

设计见 overview 05 卡「档 1 成对校验 / 档 2 模板给像素归属」。这里全是 numpy，
不依赖 torch；目标函数是对称软覆盖（与 clustering/verify.py 的 elastic 同一语义，
但在列图分辨率上做、且两张模板各自有 (dx, dy, scale)）：

    cov = ( Σ_{p∈T_A∪T_B} w(d_W(p)) + Σ_{p∈W} w(min(d_A(p), d_B(p))) ) / (|T_A|+|T_B|+|W|)
    w(d) = exp(-(d/τ)²)

- d_W：窗口墨的距离变换；d_A / d_B：各自模板墨的距离变换，按缩放档预算好；
- 位置搜索是坐标下降：固定 B 搜 A、固定 A 搜 B，粗后细；
- 全部查表都是整数平移，一轮 dy×dx 网格一次性向量化。

像素归属：窗口每个墨像素归给 d 更小的那张模板；|d_A - d_B| 很小的进「存疑带」，
再按连通体多数票平滑（小部件整块归边）。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from common import GlyphIndex, FontTemplates, ink_bbox

TAU = 3.0          # 列图分辨率下的软覆盖尺度（字高 ~90px、笔宽 ~8px）
PAD = 40           # 距离变换图四周留白，越界查表拿到大距离而不是报错
SCALES = (0.90, 1.0, 1.10)                       # 兼容旧调用
# (sx, sy)：刻本挤排时字多是**纵向**被压扁、宽度受列宽约束基本不变（exp3 v1 的 參/校、寶/氣 失败就是等比缩放伸不进去）
LEVELS = ((1.0, 1.0), (1.0, 0.9), (1.0, 0.8), (1.0, 0.7), (0.9, 0.9), (1.1, 1.1), (1.1, 1.0), (0.9, 1.0))
OVERLAP_LAMBDA = 1.0                              # 两张模板互相压住的像素，每个抵消一个被覆盖的像素


def _dt(binary: np.ndarray, pad: int = PAD) -> np.ndarray:
    """1=墨 的二值图 → 到最近墨像素的距离（含四周 pad）。"""
    h, w = binary.shape
    big = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    big[pad:pad + h, pad:pad + w] = binary.astype(np.uint8)
    inv = (1 - big).astype(np.uint8)
    d = cv2.distanceTransform(inv, cv2.DIST_L2, 3).astype(np.float32)
    return d


def _w(d: np.ndarray, tau: float = TAU) -> np.ndarray:
    return np.exp(-(d / tau) ** 2)


@dataclass
class ScaledTemplate:
    scale: tuple            # (sx, sy)
    ink: np.ndarray            # (th, tw) 二值
    ys: np.ndarray             # 墨像素坐标（模板局部）
    xs: np.ndarray
    dt: np.ndarray             # 带 PAD 的距离变换
    th: int
    tw: int


class Template:
    """一张模板（canonical 256² 二值）按目标字高缩放成几档，各自预算距离变换。"""

    def __init__(self, canon: np.ndarray, target_h: float, src: str = "", levels=LEVELS):
        self.src = src
        bb = ink_bbox(canon)
        assert bb is not None
        x0, y0, x1, y1 = bb
        crop = canon[y0:y1, x0:x1].astype(np.uint8)
        self.aspect = (x1 - x0) / max(1, (y1 - y0))
        self.levels: list[ScaledTemplate] = []
        for sx, sy in levels:
            th = max(8, int(round(target_h * sy)))
            tw = max(8, int(round(target_h * self.aspect * sx)))
            ink = cv2.resize(crop * 255, (tw, th), interpolation=cv2.INTER_AREA) >= 128
            ys, xs = np.nonzero(ink)
            self.levels.append(ScaledTemplate((sx, sy), ink.astype(np.uint8), ys, xs, _dt(ink), th, tw))


@dataclass
class Placement:
    level: int      # 缩放档下标
    y: int          # 模板左上角在窗口坐标里的 y（可为负）
    x: int

    def key(self):
        return (self.level, self.y, self.x)


class Registrar:
    """一个双格窗口上的配准器：预算窗口距离变换，提供联合打分与坐标下降。"""

    def __init__(self, win_ink: np.ndarray, tau: float = TAU):
        self.W = win_ink.astype(np.uint8)
        self.h, self.w = self.W.shape
        self.tau = tau
        self.W_dt = _dt(self.W)
        self.wy, self.wx = np.nonzero(self.W)
        self.nW = int(self.wy.size)
        bb = ink_bbox(self.W)
        self.ink_top = bb[1] if bb else 0
        self.ink_bottom = bb[3] if bb else self.h
        self.cx = float(self.wx.mean()) if self.nW else self.w / 2

    # ── 查表 ──
    def _cover_T(self, T: ScaledTemplate, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
        """模板墨被窗口墨覆盖的软计数，对一组 (y, x) 放置同时算。返回 (n_place,)"""
        Y = T.ys[None, :] + ys[:, None] + PAD
        X = T.xs[None, :] + xs[:, None] + PAD
        Y = np.clip(Y, 0, self.W_dt.shape[0] - 1); X = np.clip(X, 0, self.W_dt.shape[1] - 1)
        return _w(self.W_dt[Y, X], self.tau).sum(axis=1)

    def _d_from(self, T: ScaledTemplate, y: int, x: int) -> np.ndarray:
        """窗口每个墨像素到这张模板（放在 (y,x)）的距离。返回 (nW,)"""
        Y = np.clip(self.wy - y + PAD, 0, T.dt.shape[0] - 1)
        X = np.clip(self.wx - x + PAD, 0, T.dt.shape[1] - 1)
        return T.dt[Y, X]

    def _d_from_many(self, T: ScaledTemplate, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
        Y = np.clip(self.wy[None, :] - ys[:, None] + PAD, 0, T.dt.shape[0] - 1)
        X = np.clip(self.wx[None, :] - xs[:, None] + PAD, 0, T.dt.shape[1] - 1)
        return T.dt[Y, X]                                   # (n_place, nW)

    def score(self, A: Template, pa: Placement, B: Template, pb: Placement) -> float:
        TA, TB = A.levels[pa.level], B.levels[pb.level]
        cT = self._cover_T(TA, np.array([pa.y]), np.array([pa.x]))[0] + \
            self._cover_T(TB, np.array([pb.y]), np.array([pb.x]))[0]
        d = np.minimum(self._d_from(TA, pa.y, pa.x), self._d_from(TB, pb.y, pb.x))
        cW = _w(d, self.tau).sum()
        return float((cT + cW) / max(1, TA.ys.size + TB.ys.size + self.nW))

    def _search_one(self, T: Template, other: Template, po: Placement, center: Placement,
                    dys, dxs, levels) -> tuple[Placement, float]:
        """固定 other，在 center 附近的 (level, dy, dx) 网格上搜 T 的最优放置。"""
        TO = other.levels[po.level]
        dO = self._d_from(TO, po.y, po.x)                     # (nW,)
        cO = self._cover_T(TO, np.array([po.y]), np.array([po.x]))[0]
        # other 放好后的墨掩膜（窗口坐标 + PAD），给重叠罚查表
        Omask = np.zeros((self.h + 2 * PAD, self.w + 2 * PAD), np.uint8)
        oy = TO.ys + po.y + PAD; ox = TO.xs + po.x + PAD
        ok = (oy >= 0) & (oy < Omask.shape[0]) & (ox >= 0) & (ox < Omask.shape[1])
        Omask[oy[ok], ox[ok]] = 1
        best, best_p = -1.0, center
        grid_y, grid_x = np.meshgrid(dys, dxs, indexing="ij")
        gy = grid_y.ravel(); gx = grid_x.ravel()
        for lv in levels:
            TT = T.levels[lv]
            # 缩放档变了要保持模板中心不动
            cy = center.y + T.levels[center.level].th / 2 - TT.th / 2
            cx = center.x + T.levels[center.level].tw / 2 - TT.tw / 2
            ys = np.round(cy + gy).astype(int); xs = np.round(cx + gx).astype(int)
            cT = self._cover_T(TT, ys, xs)                                   # (n,)
            d = np.minimum(self._d_from_many(TT, ys, xs), dO[None, :])       # (n, nW)
            cW = _w(d, self.tau).sum(axis=1)
            Y = np.clip(TT.ys[None, :] + ys[:, None] + PAD, 0, Omask.shape[0] - 1)
            X = np.clip(TT.xs[None, :] + xs[:, None] + PAD, 0, Omask.shape[1] - 1)
            ov = Omask[Y, X].sum(axis=1)                                     # (n,) 与 other 重叠的模板像素数
            sc = (cT + cO + cW - OVERLAP_LAMBDA * ov) / max(1, TT.ys.size + TO.ys.size + self.nW)
            i = int(np.argmax(sc))
            if sc[i] > best:
                best, best_p = float(sc[i]), Placement(lv, int(ys[i]), int(xs[i]))
        return best_p, best

    def register(self, A: Template, B: Template, rounds: int = 2) -> tuple[Placement, Placement, float]:
        """A 顶对窗口墨顶、B 底对窗口墨底起步，坐标下降到收敛。"""
        la = A.levels[0]; lb = B.levels[0]
        pa = Placement(0, int(self.ink_top), int(round(self.cx - la.tw / 2)))
        pb = Placement(0, int(self.ink_bottom - lb.th), int(round(self.cx - lb.tw / 2)))
        coarse_dy = np.arange(-12, 13, 3); coarse_dx = np.arange(-9, 10, 3)
        fine_dy = np.arange(-3, 4, 1); fine_dx = np.arange(-3, 4, 1)
        lv_all = list(range(len(A.levels)))
        sc = -1.0
        for r in range(rounds):
            dys, dxs, lvs = (coarse_dy, coarse_dx, lv_all) if r == 0 else (fine_dy, fine_dx, lv_all)
            pa, sc = self._search_one(A, B, pb, pa, dys, dxs, lvs)
            pb, sc = self._search_one(B, A, pa, pb, dys, dxs, lvs)
        # 最后一轮极细
        pa, sc = self._search_one(A, B, pb, pa, np.arange(-1, 2), np.arange(-1, 2), [pa.level])
        pb, sc = self._search_one(B, A, pa, pb, np.arange(-1, 2), np.arange(-1, 2), [pb.level])
        return pa, pb, sc

    # ── 像素归属 ──
    def partition(self, A: Template, pa: Placement, B: Template, pb: Placement,
                  tie: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """返回 (owner, dA, dB)：owner 与窗口同形，0=背景 1=A 2=B。

        先逐像素按距离归边，|dA-dB|<tie 的像素先标 0 待定；再按连通体：
        每个连通体若一边占绝对多数（≥85%）整块归该边（小部件不被劈），
        否则逐像素归边（真粘连的大连通体），待定像素跟随最近的已定像素。
        """
        dA = self._d_from(A.levels[pa.level], pa.y, pa.x)
        dB = self._d_from(B.levels[pb.level], pb.y, pb.x)
        own_px = np.where(dA + tie < dB, 1, np.where(dB + tie < dA, 2, 0)).astype(np.uint8)
        owner = np.zeros((self.h, self.w), np.uint8)
        owner[self.wy, self.wx] = own_px
        n, lab = cv2.connectedComponents(self.W, connectivity=8)
        for i in range(1, n):
            m = lab == i
            vals = owner[m]
            nA, nB = int((vals == 1).sum()), int((vals == 2).sum())
            tot = nA + nB
            if tot == 0:
                # 全部待定：按平均距离
                sel = m[self.wy, self.wx]
                owner[m] = 1 if dA[sel].mean() <= dB[sel].mean() else 2
                continue
            if nA >= 0.85 * tot:
                owner[m] = 1
            elif nB >= 0.85 * tot:
                owner[m] = 2
            else:
                # 大连通体：待定像素按 dA<=dB 归边
                und = m & (owner == 0)
                if und.any():
                    sel = und[self.wy, self.wx]
                    owner[self.wy[sel], self.wx[sel]] = np.where(dA[sel] <= dB[sel], 1, 2)
        full_dA = np.full((self.h, self.w), np.inf, np.float32); full_dA[self.wy, self.wx] = dA
        full_dB = np.full((self.h, self.w), np.inf, np.float32); full_dB[self.wy, self.wx] = dB
        return owner, full_dA, full_dB


def per_template_fit(reg: "Registrar", A: "Template", pa: "Placement", B: "Template", pb: "Placement",
                     owner: np.ndarray | None = None) -> dict:
    """分模板贴合度：联合 cov 对「一半对一半错」的竞争字对不够敏感（对的那一半把分撑起来了），
    这里把窗口墨按归属拆开，各自与自己的模板算对称软覆盖，返回
    {covA, covB, min, ratioA, ratioB}；ratio = 该模板墨被窗口墨覆盖的比例（单向，看模板有没有多出来的笔画）。
    """
    if owner is None:
        owner, _, _ = reg.partition(A, pa, B, pb)
    out = {}
    for name, T, p, val in (("A", A, pa, 1), ("B", B, pb, 2)):
        lv = T.levels[p.level]
        sel = owner[reg.wy, reg.wx] == val                       # 归给这张模板的窗口墨像素
        # 模板墨 → 窗口墨（只看归属本模板的墨）：临时构造该子集的距离变换
        sub = np.zeros_like(reg.W); sub[reg.wy[sel], reg.wx[sel]] = 1
        sub_dt = _dt(sub)
        Y = np.clip(lv.ys + p.y + PAD, 0, sub_dt.shape[0] - 1); X = np.clip(lv.xs + p.x + PAD, 0, sub_dt.shape[1] - 1)
        cT = _w(sub_dt[Y, X], reg.tau)
        # 窗口墨（归属本模板）→ 模板墨
        d = reg._d_from(lv, p.y, p.x)[sel]
        cW = _w(d, reg.tau)
        n = int(lv.ys.size) + int(sel.sum())
        out["cov" + name] = float((cT.sum() + cW.sum()) / max(1, n))
        out["ratio" + name] = float(cT.mean()) if cT.size else 0.0
    out["min"] = min(out["covA"], out["covB"])
    return out


def owner_from_seam(win_ink: np.ndarray, seam_local: np.ndarray) -> np.ndarray:
    """一条缝（窗口局部坐标、每 x 一个 y）→ owner 图（1=上 2=下），只在墨像素上有值。"""
    h, w = win_ink.shape
    ys = np.arange(h)[:, None]
    above = ys < np.asarray(seam_local[:w])[None, :]
    owner = np.where(above, 1, 2).astype(np.uint8)
    owner[win_ink == 0] = 0
    return owner


def owner_agreement(o1: np.ndarray, o2: np.ndarray) -> float:
    m = (o1 > 0) & (o2 > 0)
    return 1.0 if not m.any() else float((o1[m] == o2[m]).mean())


def seam_from_owner(owner: np.ndarray) -> tuple[np.ndarray, int]:
    """owner → 每 x 一条分界 y（上侧最低墨与下侧最高墨的中点；某列只有一边就取该边缘）。
    返回 (seam_local, n_interleaved)：n_interleaved = 上侧墨低于下侧墨的列数（缝表达不了）。"""
    h, w = owner.shape
    seam = np.zeros(w, int)
    inter = 0
    last = h // 2
    for x in range(w):
        col = owner[:, x]
        a = np.nonzero(col == 1)[0]; b = np.nonzero(col == 2)[0]
        if a.size and b.size:
            if a.max() >= b.min():
                inter += 1
            last = int((a.max() + b.min()) // 2 + 1)
        elif a.size:
            last = int(a.max() + 1)
        elif b.size:
            last = int(b.min())
        seam[x] = last
    return seam, inter


class TemplateBank:
    """按字取模板：本书真刻例（排除待测格）优先，字体兜底。"""

    def __init__(self, glyphs: GlyphIndex | None = None, fonts: FontTemplates | None = None,
                 n_exemplars: int = 2):
        self.glyphs = glyphs or GlyphIndex()
        self.fonts = fonts or FontTemplates()
        self.n = n_exemplars

    def get(self, ch: str, target_h: float, exclude=None, allow_font: bool = True,
            prefer: str = "glyph") -> list[Template]:
        out: list[Template] = []
        if prefer in ("glyph", "both"):
            for i, ex in enumerate(self.glyphs.exemplars(ch, exclude=exclude, n=self.n)):
                out.append(Template(ex, target_h, src=f"glyph{i}"))
        if (not out or prefer in ("font", "both")) and allow_font:
            f = self.fonts.render(ch)
            if f is not None:
                out.append(Template(f[1], target_h, src=f"font:{f[0]}"))
        return out
