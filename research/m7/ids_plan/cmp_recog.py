"""部件识别器按册留出对比（M7 IDS 通用计算第二步，2026-10-22）。sheldon 核过错例：标注与人标切线都对，错在部件识别。
所以这里**固定用人标切线**切出判别那一段，只换识别器：
  nn        现做法：归一 32×32、模糊 Dice 最近邻
  hog32     HOG（4×4 格）＋岭回归（一对多）
  hog48x6   归一 48×48、HOG 6×6 格＋岭回归
  asp       保留宽高比（补白成方）再 48×48 HOG 6×6＋岭回归
  pix       像素 32×32＋岭回归
`--leaf`：判别叶子在更深一层时再切一刀取叶子（见 cmp_cutter.make_extract）。
用法：python research/m7/ids_plan/cmp_recog.py xu --dataset <dataset> [--leaf]"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from cmp_cutter import ROOT, make_extract  # noqa: E402
from open_guji_cv.groups import ids_online as O  # noqa: E402
from open_guji_cv.groups.ids_parts import hog, similarity  # noqa: E402
from open_guji_cv.groups.ids_plan import derive_plan  # noqa: E402
from open_guji_cv.groups.ids_segment import ink_of  # noqa: E402
from open_guji_cv.groups.ids_two import cut_mask  # noqa: E402
from open_guji_cv.groups.registry import GROUPS  # noqa: E402


def raw_part(img, cut, orient, which):
    """切线分出的那一段，裁到墨迹外框的 0–1 墨迹图（不缩放）。"""
    m = cut_mask(img.shape, cut, orient)
    ink = ink_of(img) & (m == which)
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    return ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)


def resize(a, s, keep_aspect=False):
    if keep_aspect:
        h, w = a.shape
        n = max(h, w)
        sq = np.zeros((n, n), np.float32)
        sq[(n - h) // 2:(n - h) // 2 + h, (n - w) // 2:(n - w) // 2 + w] = a
        a = sq
    return np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((s, s), Image.BILINEAR), np.float32) / 255


FEATS = {
    "hog32": lambda a: hog(resize(a, 32), 4),
    "hog48x6": lambda a: hog(resize(a, 48), 6),
    "asp": lambda a: hog(resize(a, 48, True), 6),
    "pix": lambda a: resize(a, 32).ravel(),
}


def ridge_fit(X, y, classes, lam):
    X = np.c_[X, np.ones(len(X))]
    Y = np.array([[1.0 if c == k else -1.0 for k in classes] for c in y])
    return np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ Y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--leaf", action="store_true")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--lam", type=float, default=1.0)
    ap.add_argument("--all", action="store_true",
                    help="用组内全部人裁格（含没标切线的），切线一律用形状先验折线（先验只取有人标切线的格）")
    a = ap.parse_args()
    g = a.group
    plan = derive_plan("".join(sorted(GROUPS[g].members)), ROOT / "config" / "groups" / g)
    orient, which = plan.orient, plan.diff[0]
    rows, _ = O._pool(g, Path(a.dataset))
    if a.all:
        from cmp_cutter import mean_shape, prior_seam
        cells, _ = O._whole_cells(g, Path(a.dataset))
        vv = sorted({c[2] for c in cells})
        fo = {v: k % a.folds for k, v in enumerate(vv)}
        # 先验形状按折取：判某格时只用其他折（其他册）的人标切线求平均形状，不漏留出册的信息
        shp = {k: mean_shape([cut for i, _f, _img, cut in rows if fo.get(i.split(":")[0]) != k], orient)
               for k in range(a.folds)}
        rows = [(i, f, img, prior_seam(img, shp[fo[v]], orient)) for f, img, v, i in cells]
        rows = [r for r in rows if r[3] is not None]
    if a.leaf:
        ext = make_extract(plan, orient, which, True)
        def part(img, cut):
            p = ext(img, cut)          # 已归一 32×32（norm_part）
            return None if p is None else p
    else:
        def part(img, cut):
            return raw_part(img, cut, orient, which)
    data = [(i, f, part(img, cut)) for i, f, img, cut in rows]
    data = [d for d in data if d[2] is not None]
    vols = sorted({d[0].split(":")[0] for d in data})
    fold_of = {v: k % a.folds for k, v in enumerate(vols)}
    classes = sorted({d[1] for d in data})
    rec = {m: [] for m in ["nn", *FEATS]}
    for k in range(a.folds):
        te = [d for d in data if fold_of[d[0].split(":")[0]] == k]
        tr = [d for d in data if fold_of[d[0].split(":")[0]] != k]
        if not te:
            continue
        nn_bank = {}
        for _i, f, p in tr:
            nn_bank.setdefault(f, []).append(resize(p, 32))
        for i, f, p in te:
            x = resize(p, 32)
            sc = sorted(((max(similarity(x, t) for t in ts), c) for c, ts in nn_bank.items()), reverse=True)
            rec["nn"].append((i, f, sc[0][1], sc[0][0] - sc[1][0]))
        for name, fe in FEATS.items():
            W = ridge_fit(np.array([fe(p) for _i, _f, p in tr]), [f for _i, f, _p in tr], classes, a.lam)
            for i, f, p in te:
                s = np.r_[fe(p), 1.0] @ W
                o = np.argsort(-s)
                rec[name].append((i, f, classes[o[0]], float(s[o[0]] - s[o[1]])))
    out = {}
    for name, rs in rec.items():
        wrong = [r for r in rs if r[2] != r[1]]
        th = max((r[3] for r in wrong), default=-1)
        out[name] = {"right": len(rs) - len(wrong), "wrong": len(wrong),
                     "zero_err_cover": round(sum(1 for r in rs if r[2] == r[1] and r[3] > th) / len(rs), 3),
                     "wrong_cells": [(r[0], r[1], r[2], round(r[3], 3)) for r in wrong]}
    print(json.dumps({"group": g, "cells": len(data), "leaf": a.leaf, "result": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
