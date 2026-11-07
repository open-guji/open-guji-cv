"""逐笔模板配准：已知字码时，把模板逐笔贴到刻本字图上。

1. 字图：二值化、细化、剪毛刺；字身小于 upscale_below 先放大。
2. 模板按外框对到骨架外框，再做整体仿射 ICP（模板点↔骨架点双向最近邻）。
3. 骨架点竞争归属到最近的那一笔，每笔各自做相似变换 ICP（限旋转、缩放、漂移）。
   被钉住的笔（pin 指定下标，或 pin_short>0 时短于字身这么多的笔）不做这一步，信模板位置，不自己去找墨——
   否则 玉 的点会滑到 王 第三横的上翘三角上（研究第五轮）。
4. 每笔非刚性贴合（位移沿笔平滑），两头沿笔势外推到墨边。
5. 量每笔「落墨率」（笔在不在墨上）和「独占率」（这一笔的墨有没有被别的笔解释掉）。

纯函数，无全局状态。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.spatial import cKDTree

from ._ink import arclen, binarize, clean_cell, extend_tip, ink_bbox, out_dir, prune_spurs, resample, stroke_width, thin
from .template import StrokeTemplate


@dataclass(frozen=True)
class RegParams:
    upscale_to: int = 200          # 字身小于 upscale_below 先放大到约这么大
    upscale_below: int = 160
    spur_len: float = 1.2          # 剪毛刺长度（笔宽倍数）
    global_iters: int = 25
    global_cut: float = 0.2        # 整体 ICP 配对距离上限（字身倍数）
    local_iters: int = 12
    max_rot_deg: float = 12.0      # 逐笔旋转上限
    scale_range: tuple = (0.8, 1.25)
    max_drift: float = 0.12        # 逐笔漂移上限（字身倍数）
    pin_short: float = 0.0         # >0：短于字身这么多的笔不做逐笔配准、不自己找墨
    pin: tuple = ()                # 这几笔（下标）不做逐笔配准、不自己找墨，信模板位置。差一笔验的那一笔用这个：
                                   # 按长短钉不稳（玉 的点贴完约 0.15 字身，正卡在阈值上，研究移植时翻过 3 格）
    pin_search: float = 0.1        # 钉住的笔在墨框里就近找「别的笔解释不了的残墨」，最多平移这么远（字身倍数）；0＝纹丝不动
    pin_dark: float = 0.0          # >0：钉住的笔只认够黑的墨（灰度 ≤ 墨中位＋pin_dark×(纸中位−墨中位)）；浅灰噪点、透字不算
    pin_min_area: float = 0.5      # 残墨至少这么多（笔宽²）才让钉住的笔去找；太小是噪点
    pin_tol: float = 0.2           # 钉住的笔量落墨时离墨多近才算（笔宽倍数）；收紧后小墨点只算盖住一小段（殿本留出异判 106→约 50）
    pin_min_frac: float = 0.8      # 找到的残墨块至少要有这一笔应有墨量（笔长×笔宽）的这么多；噪点、碎屑不够
    pin_blob: float = 0.3          # 残墨团块长边超过字身这么多（切图带进来的框线、漏掉的整笔）不让钉住的笔去找
    snap_radius: float = 2.0       # 非刚性贴合半径（笔宽倍数）
    tip_extend: float = 3.0        # 两头外推上限（笔宽倍数）
    clean: bool = True             # 先去贴边碎墨与界栏线（clean_cell）；按页裁的字块要开
    excl_gap: float = 1.2          # 独占：离别的笔多远才算这笔自己的墨（笔宽倍数）

    def to_json(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


@dataclass
class FitStroke:
    name: str
    pts: np.ndarray                # 贴好的轨迹 (n, 2)，原图坐标 (y, x)
    start: tuple = (0.0, 0.0)      # 外推到墨边的起点
    end: tuple = (0.0, 0.0)
    on_ink: float = 0.0            # 这一笔有多少落在墨上
    excl: float = 0.0              # 这一笔的墨有多少没被别的笔解释掉


@dataclass
class Fit:
    strokes: list = field(default_factory=list)
    cover: float = 0.0             # 骨架点有多少被某一笔解释（贴得好不好）
    w: float = 0.0                 # 笔宽（原图像素）
    size: float = 0.0              # 字身（原图像素）
    scale: float = 1.0             # 内部放大倍数
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)   # 墨框 (y0, x0, y1, x1)，原图坐标
    ink_frac: float = 0.0          # 墨框里墨占多少；切坏成黑条的格很高（全唐文 005:1:2:2）


def _fit_affine(src, dst, reg, prev):
    n = len(src)
    X = np.hstack([src, np.ones((n, 1))])
    return np.linalg.lstsq(X.T @ X + reg * np.eye(3), X.T @ dst + reg * prev, rcond=None)[0]


def _apply(M, p):
    return np.hstack([p, np.ones((len(p), 1))]) @ M


def _fit_similarity(src, dst):
    """Umeyama 相似变换，返回 s, R, t。"""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    a, b = src - mu_s, dst - mu_d
    U, D, Vt = np.linalg.svd(b.T @ a / len(src))
    Sg = np.eye(2)
    if np.linalg.det(U @ Vt) < 0:
        Sg[1, 1] = -1
    R = U @ Sg @ Vt
    var = (a ** 2).sum() / len(src)
    s = (D * np.diag(Sg)).sum() / var if var > 0 else 1.0
    return s, R, mu_d - s * R @ mu_s


def _blobs(pts: np.ndarray, shape, max_side: float) -> list:
    """残墨按连通块分开，只留长边不超过 max_side 的块（框线、漏掉的整笔不要）。"""
    if not len(pts):
        return []
    m = np.zeros(shape, np.uint8)
    iy, ix = pts[:, 0].astype(int), pts[:, 1].astype(int)
    m[iy, ix] = 1
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    li = lab[iy, ix]
    return [pts[li == i] for i in range(1, n)
            if max(st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]) <= max_side]


def register(gray: np.ndarray, tpl: StrokeTemplate, params: RegParams | None = None) -> Fit:
    p = params or RegParams()
    # ---- 字图（小图放大）
    ink0 = binarize(gray)
    if p.clean:
        ink0 = clean_cell(ink0)
    if not ink0.any():
        return Fit(strokes=[FitStroke(s.name, s.pts * 0) for s in tpl.strokes], bbox=ink_bbox(ink0))
    ys, xs = np.nonzero(ink0)
    size0 = max(np.ptp(ys), np.ptp(xs))
    f = 1.0 if size0 >= p.upscale_below else p.upscale_to / max(size0, 1)
    g = gray if f == 1.0 else cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    ink = binarize(g)
    if p.clean:
        ink = clean_cell(ink)
    ys, xs = np.nonzero(ink)
    size = float(max(np.ptp(ys), np.ptp(xs)))
    sk = thin(ink)
    w = stroke_width(ink, sk)
    sk = prune_spurs(sk, maxlen=max(4, p.spur_len * w))
    skp = np.argwhere(sk > 0).astype(float)
    tree = cKDTree(skp)
    dt_out = cv2.distanceTransform((1 - ink).astype(np.uint8), cv2.DIST_L2, 5)

    # ---- 模板外框对骨架外框
    allp = np.vstack([s.pts for s in tpl.strokes])
    lo, hi = allp.min(0), allp.max(0)
    slo, shi = skp.min(0), skp.max(0)
    sc = (shi - slo) / np.maximum(hi - lo, 1)
    T = [(s.name, (s.pts - lo) * sc + slo) for s in tpl.strokes]

    # ---- 整体仿射 ICP（双向）
    M = np.vstack([np.eye(2), np.zeros((1, 2))])
    base = np.vstack([q for _, q in T])
    cut = p.global_cut * size
    for _ in range(p.global_iters):
        cur = _apply(M, base)
        d1, i1 = tree.query(cur)
        d2, i2 = cKDTree(cur).query(skp)
        src = np.vstack([base[d1 < cut], base[i2[d2 < cut]]])
        dst = np.vstack([skp[i1[d1 < cut]], skp[d2 < cut]])
        if len(src) < 6:
            break
        M = _fit_affine(src, dst, reg=len(src) * 0.02, prev=M)
    T = [(nm, _apply(M, q)) for nm, q in T]

    # ---- 逐笔相似 ICP，骨架点竞争归属
    short = [k in p.pin or (p.pin_short > 0 and arclen(q) < p.pin_short * size) for k, (_, q) in enumerate(T)]
    P = [q.copy() for _, q in T]
    lim = p.max_drift * size
    for _ in range(p.local_iters):
        owner_pts = np.vstack(P)
        owner_id = np.concatenate([np.full(len(q), k) for k, q in enumerate(P)])
        d_own, i_own = cKDTree(owner_pts).query(skp)
        own = owner_id[i_own]
        for k in range(len(P)):
            if short[k]:
                continue
            mine = skp[(own == k) & (d_own < 0.15 * size)]
            if len(mine) < 3:
                continue
            d, i = cKDTree(mine).query(P[k])
            ok = d < 0.12 * size
            if ok.sum() < 2:
                continue
            _, i2 = cKDTree(P[k]).query(mine)
            src = np.vstack([P[k][ok], P[k][i2]])
            dst = np.vstack([mine[i[ok]], mine])
            s, R, _t = _fit_similarity(src, dst)
            ang = math.degrees(math.atan2(R[1, 0], R[0, 0]))
            s = float(np.clip(s, *p.scale_range))
            if abs(ang) > p.max_rot_deg:
                a = math.radians(np.sign(ang) * p.max_rot_deg)
                R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            t = dst.mean(0) - s * (R @ src.mean(0))
            newP = (s * (R @ P[k].T)).T + t
            newP = P[k] + 0.6 * (newP - P[k])
            drift = newP.mean(0) - T[k][1].mean(0)
            nd = np.linalg.norm(drift)
            if nd > lim:
                newP -= drift * (1 - lim / nd)
            P[k] = newP

    # ---- 逐笔非刚性贴合
    owner_pts = np.vstack(P)
    owner_id = np.concatenate([np.full(len(q), k) for k, q in enumerate(P)])
    d_own, i_own = cKDTree(owner_pts).query(skp)
    own = owner_id[i_own]
    fitted = []
    ker = np.ones(5) / 5
    for k, q0 in enumerate(P):
        q = q0.copy()
        mine = skp[(own == k) & (d_own < 2.5 * w)]
        if len(mine) >= 2 and not short[k]:
            tk = cKDTree(mine)
            for _ in range(4):
                d, i = tk.query(q)
                disp = np.where((d < p.snap_radius * w)[:, None], mine[i] - q, 0.0)
                disp = np.stack([np.convolve(disp[:, j], ker, mode="same") for j in range(2)], 1)
                q = q + 0.7 * disp
        fitted.append(q)

    # ---- 落墨率、独占率、起止点
    H, W = ink.shape

    def on_ink(q, dt=dt_out, tol=0.6):
        iy = np.clip(np.round(q[:, 0]).astype(int), 0, H - 1)
        ix = np.clip(np.round(q[:, 1]).astype(int), 0, W - 1)
        return dt[iy, ix] <= tol * w

    tips, ext = [], []
    for q in fitted:
        s0 = extend_tip(ink, q[0], -out_dir(q, w), p.tip_extend * w)
        e0 = extend_tip(ink, q[-1], -out_dir(q[::-1], w), p.tip_extend * w)
        tips.append((s0, e0))
        ext.append(resample(np.vstack([np.array(s0), q, np.array(e0)]), 1.0))
    # ---- 钉住的笔：只在模板位置附近平移去找别的笔解释不了的残墨（横末上翘三角贴着横，不算残墨）
    dark = ink
    if p.pin_dark > 0 and ink.any() and (ink == 0).any():
        im, bg = float(np.median(g[ink > 0])), float(np.median(g[ink == 0]))
        dark = (ink > 0) & (g <= im + p.pin_dark * (bg - im))
    if p.pin_search > 0 and any(short):
        inkp = np.argwhere(dark > 0).astype(float)
        R = p.pin_search * size
        for k in [k for k in range(len(fitted)) if short[k]]:
            others = [ext[j] for j in range(len(ext)) if j != k]
            if not others:
                continue
            od, _ = cKDTree(np.vstack(others)).query(inkp)
            resid = inkp[od > p.excl_gap * w]
            blobs = _blobs(resid, ink.shape, p.pin_blob * size)
            c = fitted[k].mean(0)
            L = arclen(fitted[k])
            need = max(3.0, p.pin_min_area * w * w, p.pin_min_frac * L * w)
            cand = [b for b in blobs if len(b) >= need and np.linalg.norm(b.mean(0) - c) < R + L / 2]
            if not cand:
                continue
            near = max(cand, key=len)
            shift = near.mean(0) - c
            n = np.linalg.norm(shift)
            if n > R:
                shift *= R / n
            q = fitted[k] + shift
            fitted[k] = q
            s0 = extend_tip(ink, q[0], -out_dir(q, w), p.tip_extend * w)
            e0 = extend_tip(ink, q[-1], -out_dir(q[::-1], w), p.tip_extend * w)
            tips[k] = (s0, e0)
            ext[k] = resample(np.vstack([np.array(s0), q, np.array(e0)]), 1.0)
    dt_dark = cv2.distanceTransform((1 - dark.astype(np.uint8)), cv2.DIST_L2, 5) if dark is not ink else dt_out
    out = []
    for k, ((nm, _), q) in enumerate(zip(T, fitted)):
        if short[k]:  # 钉住的笔按 1px 重采样、容差收紧：小墨点只盖住一小段，不算整笔
            qq = resample(q, 1.0)
            oi = on_ink(qq, dt_dark, p.pin_tol)
            q_meas = qq
        else:
            oi = on_ink(q)
            q_meas = q
        others = [ext[j] for j in range(len(ext)) if j != k]
        if others:
            od, _ = cKDTree(np.vstack(others)).query(q_meas)
            ex = oi & (od > p.excl_gap * w)
        else:
            ex = oi
        s0, e0 = tips[k]
        out.append(FitStroke(name=nm, pts=q / f, on_ink=float(oi.mean()), excl=float(ex.mean()),
                             start=(s0[0] / f, s0[1] / f), end=(e0[0] / f, e0[1] / f)))
    cover = float((cKDTree(np.vstack(fitted)).query(skp)[0] < 1.5 * w).mean())
    bb = ink_bbox(ink)
    area = max(1.0, (bb[2] - bb[0] + 1) * (bb[3] - bb[1] + 1))
    return Fit(strokes=out, cover=cover, w=w / f, size=size / f, scale=f, bbox=tuple(v / f for v in bb),
               ink_frac=float(ink.sum()) / area)


__all__ = ["RegParams", "FitStroke", "Fit", "register"]
