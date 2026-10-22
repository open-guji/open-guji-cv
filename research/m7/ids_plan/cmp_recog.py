"""部件识别器按册留出对比（M7 IDS 通用计算第二步，2026-10-22）。sheldon 核过错例：标注与人标切线都对，错在部件识别。
所以这里**固定用人标切线**切出判别那一段，只换识别器：
  nn        现做法：归一 32×32、模糊 Dice 最近邻
  hog32     HOG（4×4 格）＋岭回归（一对多）
  hog48x6   归一 48×48、HOG 6×6 格＋岭回归
  asp       保留宽高比（补白成方）再 48×48 HOG 6×6＋岭回归
  pix       像素 32×32＋岭回归
`--leaf`：判别叶子在更深一层时再切一刀取叶子（见 cmp_cutter.make_extract）。
用法：python research/m7/ids_plan/cmp_recog.py xu --dataset <dataset> [--leaf] [--cutter human|prior|unet_own|unet_comp]"""
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


def fold_cutter(name, k, rows, fo, orient, plan, ds, epochs):
    """第 k 折的切法：只用其他折（其他册）的人标切线建。返回 `img -> 折线`。"""
    from cmp_cutter import comp_pool, mean_shape, prior_seam
    train = [(img, cut) for i, _f, img, cut in rows if fo.get(i.split(":")[0]) != k]
    if name == "human":
        return None
    if name == "prior":
        shp = mean_shape([c for _img, c in train], orient)
        return lambda img: prior_seam(img, shp, orient)
    from open_guji_cv.groups.ids_unet import NpNet, predict_prob_np, prob_to_polyline2
    if name == "unet_comp":
        held = {v for v, kk in fo.items() if kk == k}
        train, _ = comp_pool(ds, plan, 1 - plan.diff[0], held)
    net = NpNet.from_torch(O._train_unet2(train, orient, epochs=epochs))
    return lambda img: prob_to_polyline2(predict_prob_np(net, img), orient)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--leaf", action="store_true")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--lam", type=float, default=1.0)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--cutter", default="human", choices=["human", "prior", "unet_own", "unet_comp"],
                    help="human：只用有人标切线的格；其余：组内全部人裁格，模板格与测试格都用这一折的同一切法切（切法只用其他册建）")
    a = ap.parse_args()
    g, ds = a.group, Path(a.dataset)
    plan = derive_plan("".join(sorted(GROUPS[g].members)), ROOT / "config" / "groups" / g)
    orient, which = plan.orient, plan.diff[0]
    rows, _ = O._pool(g, ds)
    ext = make_extract(plan, orient, which, True) if a.leaf else (lambda img, cut: raw_part(img, cut, orient, which))
    if a.cutter == "human":
        cells = [(f, img, i.split(":")[0], i, cut) for i, f, img, cut in rows]
    else:
        cells = [(f, img, v, i, None) for f, img, v, i in O._whole_cells(g, ds)[0]]
    vols = sorted({c[2] for c in cells})
    fo = {v: k % a.folds for k, v in enumerate(vols)}
    classes = sorted({c[0] for c in cells})
    rec = {m: [] for m in ["nn", *FEATS]}
    for k in range(a.folds):
        if not any(fo[c[2]] == k for c in cells):
            continue
        cut_of = fold_cutter(a.cutter, k, rows, fo, orient, plan, ds, a.epochs)
        data = []
        for f, img, v, i, cut in cells:
            pl = cut if cut_of is None else cut_of(img)
            p = ext(img, pl) if pl is not None else None
            if p is not None:
                data.append((i, f, p, fo[v] == k))
        tr = [d[:3] for d in data if not d[3]]
        te = [d[:3] for d in data if d[3]]
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
        print("fold", k, "done", file=sys.stderr, flush=True)
    out = {}
    for name, rs in rec.items():
        wrong = [r for r in rs if r[2] != r[1]]
        th = max((r[3] for r in wrong), default=-1)
        out[name] = {"right": len(rs) - len(wrong), "wrong": len(wrong),
                     "zero_err_cover": round(sum(1 for r in rs if r[2] == r[1] and r[3] > th) / len(rs), 3),
                     "wrong_cells": [(r[0], r[1], r[2], round(r[3], 3)) for r in wrong]}
    print(json.dumps({"group": g, "cells": len(rec["nn"]), "leaf": a.leaf, "cutter": a.cutter, "result": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
