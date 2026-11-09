# -*- coding: utf-8 -*-
"""5a 逐对相似度的候选算法（只给 eval_sim_bench.py 用，不进包，改它不让任何册过期）。

每个算法 f(a, b) -> float 或 list[float]（特征向量，交给融合层），a＝查询、b＝库刻例，64×64 uint8 {0,1}。
生产的判据是 `verify.verify_pair_elastic`（软覆盖 τ=1.5 ＋ 16×16 分块 ±1 弹性，cov 再按分位映射回 coverage 刻度）。
这里按它的内部函数改写，逐项拆开：两方向覆盖、τ、块大小、局部残差、方向一致、HOG。
结论与数见 ai-team domain/CV/字形领域/5a相似度算法-2026-11-09.md。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.clustering import verify as V  # noqa: E402
from open_guji_cv.clustering.features import get_feature  # noqa: E402

_HOG = get_feature("hog")
def prod(a, b):
    return V.verify_pair_elastic(a, b).f1


def coverage(a, b):
    return V.verify_pair_cov(a, b).f1


def hog(a, b):
    f = _HOG.extract(np.stack([a, b]))
    return float(f[0] @ f[1])


def _elastic_dirs(a, b, tau=V.ELASTIC_TAU, block=V.ELASTIC_BLOCK, local=V.ELASTIC_LOCAL,
                  max_shift=V.MAX_SHIFT, scales=V.SCALES, obj='mean'):
    """生产 _elastic_align 的改写：分别返回两方向覆盖率，并按 obj 选最优位移。
    返回 (score, cov_a_by_b, cov_b_by_a, shift(dx,dy), scale)。"""
    size = a.shape[0]
    na = int(a.sum())
    if na == 0 or int(b.sum()) == 0:
        return 0.0, 0.0, 0.0, (0, 0), 1.0
    offsets, pick, radius, span, stride, n_side = V._grids(size, block, local, max_shift)
    _, _, wa, base_a, sa = V._prepare(a, 1.0, tau, block, span, stride, n_side)
    W, idx_a = V._query_tables(a, wa, base_a, offsets, tau, block, span, stride)
    best = None
    for scale in scales:
        b_s, nb, wb, base_b, sb = V._prepare(b, scale, tau, block, span, stride, n_side)
        if nb == 0:
            continue
        t_b = np.add.reduceat(np.take(W, base_b, axis=1), sb, axis=1)
        t_a = np.add.reduceat(np.take(wb, idx_a), sa, axis=1)
        cb = V._window_max(t_b, span, local).sum(axis=1) / nb   # b 的墨被 a 覆盖
        ca = V._window_max(t_a, span, local).sum(axis=1) / na   # a 的墨被 b 覆盖
        if obj == 'mean':
            s = (ca * na + cb * nb) / (na + nb)
        elif obj == 'min':
            s = np.minimum(ca, cb)
        elif obj == 'hm':
            s = 2 * ca * cb / np.maximum(ca + cb, 1e-9)
        elif obj == 'geo':
            s = np.sqrt(ca * cb)
        k = int(np.lexsort((radius, -s))[0])
        key = (-float(s[k]), radius[k], abs(scale - 1.0))
        if best is None or key < best[0]:
            sh = (max_shift - k % (2 * max_shift + 1), max_shift - k // (2 * max_shift + 1))
            best = (key, float(s[k]), float(ca[k]), float(cb[k]), sh, scale)
    if best is None:
        return 0.0, 0.0, 0.0, (0, 0), 1.0
    return best[1:]


def mk_elastic(**kw):
    def f(a, b):
        return _elastic_dirs(a, b, **kw)[0]
    return f


def mk_elastic_wmax(lam):
    """生产 cov 减去局部残差惩罚（wmax 已在生产算，只是没进分数）。"""
    def f(a, b):
        v = V.verify_pair_elastic(a, b)
        w = v.diff_blob_ratio
        return v.f1 - lam * (w / 100.0)
    return f



# ---------------- 方向感知软覆盖 ----------------
_ANG = np.array([0, np.pi / 4, np.pi / 2, 3 * np.pi / 4])


def orient(binary, sig_g=1.0, sig_t=2.0):
    """逐墨点笔画方向分布 (4, H, W)，按方向软分配，低相干处摊平。"""
    f = cv2.GaussianBlur(binary.astype(np.float32), (0, 0), sig_g)
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), sig_t)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), sig_t)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), sig_t)
    th = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2   # 笔画方向
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
    w = np.maximum(0, np.cos(2 * (th[None] - _ANG[:, None, None])))
    w = w / (w.sum(0, keepdims=True) + 1e-6)
    w = coh[None] * w + (1 - coh[None]) * 0.25
    return w.astype(np.float32)


def _ofields(binary, tau, pad, thr=0.35):
    o = orient(binary)
    n = binary.shape[0]
    out = np.zeros((4, n + 2 * pad, n + 2 * pad), np.float32)
    for k in range(4):
        m = (binary > 0) & (o[k] >= thr)
        if m.any():
            dist = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 5)
            out[k, pad:pad + n, pad:pad + n] = np.exp(-(dist / tau) ** 2)
    return o, out


def _ocov(src, dst, tau, block, local, mix):
    """src 墨点被 dst 覆盖的量：mix·方向一致覆盖 + (1-mix)·普通覆盖；每块各自搜 ±local。"""
    size = src.shape[0]
    n_side = (size + block - 1) // block
    ys, xs = np.nonzero(src)
    if len(ys) == 0:
        return 0.0, 0
    os_, _ = _ofields(src, tau, local) if mix > 0 else (None, None)
    _, fd = _ofields(dst, tau, local) if mix > 0 else (None, None)
    stride = size + 2 * local
    wd = V._weight_field(dst, tau, local).reshape(stride, stride)
    gid = (ys // block) * n_side + (xs // block)
    cands = []
    for ly in range(-local, local + 1):
        for lx in range(-local, local + 1):
            yy, xx = ys + local + ly, xs + local + lx
            plain = wd[yy, xx]
            if mix > 0:
                ori = (os_[:, ys, xs] * fd[:, yy, xx]).sum(0)
                v = mix * ori + (1 - mix) * plain
            else:
                v = plain
            cands.append(v)
    cand = np.stack(cands)
    sums = np.stack([np.bincount(gid, weights=c, minlength=n_side * n_side) for c in cand])
    return float(sums.max(axis=0).sum()), len(ys)


def mk_orient(tau=2.0, mix=1.0, block=16, local=1, align_tau=None):
    at = align_tau or tau
    def f(a, b):
        raw, (dx, dy), scale, b_s = V._elastic_align(a, b, V.MAX_SHIFT, V.SCALES, at, block, local, None)
        if b_s is None:
            return 0.0
        size = a.shape[0]; ms = V.MAX_SHIFT
        padded = np.zeros((size + 2 * ms, size + 2 * ms), np.uint8)
        padded[ms:ms + size, ms:ms + size] = b_s
        bal = V._shifted_view(padded, dx, dy, size, ms)
        ca, na = _ocov(a, bal, tau, block, local, mix)
        cb, nb = _ocov(bal, a, tau, block, local, mix)
        return (ca + cb) / max(1, na + nb)
    return f




def _miss_max(src, dst, tau, local, win=12, block=16):
    """对齐后 src 未被 dst 覆盖的权重，在 win×win 窗口里的最大和。"""
    size = src.shape[0]; n_side = (size + block - 1) // block
    ys, xs = np.nonzero(src)
    if len(ys) == 0:
        return 0.0
    stride = size + 2 * local
    wd = V._weight_field(dst, tau, local).reshape(stride, stride)
    cand = np.stack([wd[ys + local + ly, xs + local + lx] for ly in range(-local, local + 1) for lx in range(-local, local + 1)])
    gid = (ys // block) * n_side + (xs // block)
    sums = np.stack([np.bincount(gid, weights=c, minlength=n_side * n_side) for c in cand])
    bl = sums.argmax(0)[gid]
    w = cand[bl, np.arange(len(ys))]
    miss = np.zeros((size, size), np.float32); miss[ys, xs] = 1 - w
    return float(cv2.boxFilter(miss, -1, (win, win), normalize=False).max())


FEAT_NAMES = ['raw2', 'ca1', 'cb1', 'ca2', 'cb2', 'ca3', 'cb3', 'oa', 'ob', 'ma', 'mb', 'ma6', 'mb6', 'hog', 'lr_ink', 'rigid', 'shift', 'scale']


def features(a, b):
    raw, (dx, dy), scale, b_s = V._elastic_align(a, b, V.MAX_SHIFT, V.SCALES, 2.0, 16, 1, None)
    if b_s is None:
        return [0.0] * len(FEAT_NAMES)
    size = a.shape[0]; ms = V.MAX_SHIFT
    padded = np.zeros((size + 2 * ms, size + 2 * ms), np.uint8)
    padded[ms:ms + size, ms:ms + size] = b_s
    bal = V._shifted_view(padded, dx, dy, size, ms).copy()
    na, nb = int(a.sum()), max(1, int(bal.sum()))
    out = [raw]
    for t in (1.0, 2.0, 3.0):
        out += [_ocov(a, bal, t, 16, 1, 0)[0] / na, _ocov(bal, a, t, 16, 1, 0)[0] / nb]
    out += [_ocov(a, bal, 2.0, 16, 1, 1.0)[0] / na, _ocov(bal, a, 2.0, 16, 1, 1.0)[0] / nb]
    out += [_miss_max(a, bal, 1.5, 1), _miss_max(bal, a, 1.5, 1), _miss_max(a, bal, 1.5, 1, 6), _miss_max(bal, a, 1.5, 1, 6)]
    out += [hog(a, b), float(np.log(na / nb)), V._f1(a, bal, na, nb), float(abs(dx) + abs(dy)), float(scale)]
    return out




FAST_NAMES = ['raw2', 'ca2', 'cb2', 'ma', 'mb', 'hog', 'lr_ink']


def fast_features(a, b, hogsim=None):
    """融合版：一次对齐拿双向覆盖，再量双向局部残差；hog 在生产里由 kNN 粗排白给。"""
    raw, ca, cb, (dx, dy), scale = _elastic_dirs(a, b, tau=2.0)
    size = a.shape[0]; ms = V.MAX_SHIFT
    b_s = V._rescale(b, scale)
    padded = np.zeros((size + 2 * ms, size + 2 * ms), np.uint8)
    padded[ms:ms + size, ms:ms + size] = b_s
    bal = V._shifted_view(padded, dx, dy, size, ms)
    na, nb = int(a.sum()), max(1, int(bal.sum()))
    return [raw, ca, cb, _miss_max(a, bal, 1.5, 1), _miss_max(bal, a, 1.5, 1),
            hog(a, b) if hogsim is None else hogsim, float(np.log(na / nb))]






# 融合（fast7）：一次对齐的双向覆盖＋双向局部残差＋HOG＋墨量比，Logistic 回归。
# 系数在全唐文人裁 3002 格（体检标记除外）全量拟合（eval_sim_bench.py --fit 可重出），原始特征尺度。
FAST7_COEF = {"raw2": 7.229, "ca2": 1.797, "cb2": 7.358, "ma": -0.102, "mb": -0.121, "hog": 18.167, "lr_ink": -2.43}
FAST7_BIAS = -24.884


def fast7(a, b, hogsim=None):
    f = dict(zip(FAST_NAMES, fast_features(a, b, hogsim)))
    return FAST7_BIAS + sum(FAST7_COEF[k] * f[k] for k in FAST_NAMES)


REGISTRY = {
    "prod": prod, "coverage": coverage, "hog": hog,
    "el_mean": mk_elastic(obj="mean"), "el_min": mk_elastic(obj="min"), "el_hm": mk_elastic(obj="hm"),
    "el_tau1": mk_elastic(tau=1.0), "el_tau2": mk_elastic(tau=2.0), "el_tau3": mk_elastic(tau=3.0),
    "el_tau4": mk_elastic(tau=4.0), "el_tau2_min": mk_elastic(tau=2.0, obj="min"),
    "el_loc0": mk_elastic(local=0), "el_loc2": mk_elastic(local=2),
    "el_blk8": mk_elastic(block=8), "el_blk32": mk_elastic(block=32), "el_sh5": mk_elastic(max_shift=5),
    "wmax10": mk_elastic_wmax(0.10),
    "or_t2": mk_orient(2.0, 1.0), "or_t2_m5": mk_orient(2.0, 0.5),
    "feat": features, "fast": fast_features, "fast7": fast7,
}
