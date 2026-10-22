"""切分方法按册留出对比（M7 IDS 通用计算第二步，2026-10-22）。

同一组、同一折，比较几种「切开两部件」的办法，判法都是 by_form（切下判别那一段，与各字同段模板最近邻）：
  human   人标切线（上限）
  auto    自动缝（ids_two.auto_cut）
  own     只用本组人标切线训的 U-Net
  shared  V_POOL（叙敘＋教敎＋絕絶）合训的 U-Net（现线上 xu 的做法）
  comp    固定部件池：本组＋其他组里「同一侧也是这个公共部件」的格（如 攵 在右：敘、教、敎）合训的 U-Net（sheldon 10-22 的想法）
  tmpl    固定部件定位（直线版，已证不行，保留作对照）：公共部件的平均模板，在候选直线切位上比相似度取最好的一刀
  prior   形状先验折线：训练格人标切线的平均形状当先验，在它附近（±band）用 DP 找穿墨最少的折线（sheldon 10-22：直线不行要折线）
切向、判别那一段都由 `ids_plan.derive_plan` 导出，不用手填。留出的册不进任何训练／模板。
指标：给字对／错（不设门槛）、0 错覆盖率（margin 大于最大错例 margin 的格占比）、与人标切线的墨迹归段一致率。
用法：python research/m7/ids_plan/cmp_cutter.py xu --dataset <dataset> [--methods human,auto,own,shared,comp,tmpl]
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups.ids_parts import similarity
from open_guji_cv.groups.ids_plan import derive_plan
from open_guji_cv.groups.ids_segment import ink_of
from open_guji_cv.groups.ids_two import _choose_norm, auto_cut, cut_mask, part_of
from open_guji_cv.groups.ids_unet import NpNet, predict_prob_np, prob_to_polyline2
from open_guji_cv.groups.registry import GROUPS

ROOT = Path(__file__).resolve().parents[3]


def straight(c, orient):
    return [[0.0, c], [1.0, c]] if orient == "h" else [[c, 0.0], [c, 1.0]]


def tmpl_cut(img, mean_t, orient, fixed, lo=0.25, hi=0.75, step=0.01):
    best = (-1.0, None)
    for c in np.arange(lo, hi + 1e-9, step):
        pl = straight(float(c), orient)
        p = part_of(img, pl, orient, fixed)
        if p is None:
            continue
        s = similarity(p, mean_t)
        if s > best[0]:
            best = (s, pl)
    return best[1]


#: 有人标切线的组（固定部件池从这里找同侧同部件的格）
CUT_GROUPS = ("xu", "jiao", "jue", "can")


def comp_pool(ds, plan, fixed, held):
    """其他组里，某字在 `fixed` 一侧的部件与本组公共部件相同的格（结构符也相同）。"""
    from open_guji_cv.groups.ids import load_table, parse
    from open_guji_cv.groups.ids_plan import _own_ids
    common = plan.root.sub[fixed].text
    out, used = [], {}
    for gg in CUT_GROUPS:
        table = {**load_table(), **_own_ids(ROOT / "config" / "groups" / gg)}
        rr, _ = O._pool(gg, ds)
        for i, f, img, cut in rr:
            if i.split(":")[0] in held:
                continue
            ok = False
            for seq in table.get(f, []):
                try:
                    n = parse(seq)
                except (ValueError, IndexError):
                    continue
                if n.idc == plan.idc and len(n.kids) == plan.arity and str(n.kids[fixed]) == common:
                    ok = True
            if ok:
                out.append((img, cut))
                used[f] = used.get(f, 0) + 1
    return out, used


N_PRIOR = 64


def mean_shape(cuts, orient):
    """人标折线 → 在 N_PRIOR 个采样点上的平均位置（h：各 x 处的 y；v：各 y 处的 x）。"""
    t = (np.arange(N_PRIOR) + 0.5) / N_PRIOR
    rows = []
    for cut in cuts:
        pts = sorted((q[0], q[1]) if orient == "h" else (q[1], q[0]) for q in cut)
        rows.append(np.interp(t, [a for a, _ in pts], [b for _, b in pts]))
    return np.mean(rows, axis=0)


def prior_seam(img, shape, orient, band=0.12, lam=0.6, pull=3.0, step=4):
    """以平均形状为先验的 DP 缝（h 版；v 先转置）。代价＝墨迹 + lam×|步变| + pull×偏离先验（占图高比例）。"""
    ink = ink_of(img)
    if not ink.any():
        return None
    if orient == "v":
        ink = ink.T
    h, w = ink.shape
    prior = np.interp((np.arange(w) + 0.5) / w, (np.arange(N_PRIOR) + 0.5) / N_PRIOR, shape) * h
    ys = np.arange(h)[:, None]
    cost = ink.astype(float) + pull * np.abs(ys - prior[None, :]) / h
    cost[np.abs(ys - prior[None, :]) > band * h] = np.inf
    acc = np.full((h, w), np.inf); back = np.zeros((h, w), dtype=np.int16)
    acc[:, 0] = cost[:, 0]
    for x in range(1, w):
        prev = acc[:, x - 1]
        cand = np.stack([np.r_[np.inf, prev[:-1]] + lam, prev, np.r_[prev[1:], np.inf] + lam])
        k = cand.argmin(axis=0)
        acc[:, x] = cand[k, np.arange(h)] + cost[:, x]
        back[:, x] = k - 1
    i = int(acc[:, -1].argmin()); path = [0] * w
    for x in range(w - 1, -1, -1):
        path[x] = i
        if x:
            i = min(max(i + int(back[i, x]), 0), h - 1)
    xs = list(range(0, w, step)) + [w - 1]
    pl = [[(x + 0.5) / w, (path[x] + 0.5) / h] for x in xs]
    return pl if orient == "h" else [[b, a] for a, b in pl]


def make_extract(plan, orient, which, leaf: bool):
    """判别那一段的取法。`leaf`：计划里判别叶子在更深一层（絕絶 (1,0)＝右部「色」的上半）时，
    先切出该段、裁到墨迹外框，再按子结构符自动缝第二刀，取叶子那一块。"""
    from open_guji_cv.groups.ids_parts import norm_part
    from open_guji_cv.groups.ids_plan import ORIENT, diff_leaves
    path = diff_leaves(plan)[0][0]
    sub = plan.root.sub[which]
    if not leaf or len(path) < 2 or ORIENT.get(sub.idc) is None:
        return lambda img, pl: part_of(img, pl, orient, which)
    so, sw = ORIENT[sub.idc], path[1]

    def ext(img, pl):
        m = cut_mask(img.shape, pl, orient)
        part = np.full_like(img, 255)
        part[m == which] = img[m == which]
        ink = ink_of(part)
        if not ink.any():
            return None
        ys, xs = np.where(ink)
        crop = part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        c2 = auto_cut(crop, so, 0.45)
        if c2 is None:
            return None
        m2 = cut_mask(crop.shape, c2, so)
        q = np.full_like(crop, 255)
        q[m2 == sw] = crop[m2 == sw]
        return norm_part(q)
    return ext


def agree(img, pl, human, orient):
    ink = ink_of(img)
    if pl is None or not ink.any():
        return 0.0
    a, b = cut_mask(img.shape, pl, orient), cut_mask(img.shape, human, orient)
    return float((a[ink] == b[ink]).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--leaf", action="store_true", help="判别叶子在更深一层时再切一刀取叶子")
    ap.add_argument("--methods", default="human,auto,own,shared,comp,prior")
    a = ap.parse_args()
    ds, g = Path(a.dataset), a.group
    methods = a.methods.split(",")
    plan = derive_plan("".join(sorted(GROUPS[g].members)), ROOT / "config" / "groups" / g)
    assert plan.mode == "split" and plan.arity == 2 and len(plan.diff) == 1, plan
    orient, which = plan.orient, plan.diff[0]
    fixed = 1 - which
    print(f"{g}: plan {plan.frame} orient={orient} which={which}", flush=True)
    extract = make_extract(plan, orient, which, a.leaf)
    spec = O.IdsSpec(frame="", orient=orient, prior=0.5, which=which, by_form=True)
    rows, _ = O._pool(g, ds)
    vols = sorted({r[0].split(":")[0] for r in rows})
    fold_of = {v: k % a.folds for k, v in enumerate(vols)}
    rec = defaultdict(list)          # 方法 → [(id, 字, 判, margin, 归段一致率)]
    members = GROUPS[g].members
    for k in range(a.folds):
        test = [r for r in rows if fold_of[r[0].split(":")[0]] == k]
        if not test:
            continue
        rest = [r for r in rows if fold_of[r[0].split(":")[0]] != k]
        held = {v for v in vols if fold_of[v] == k}
        cutters = {}
        if "human" in methods:
            cutters["human"] = lambda img, cut: cut
        if "auto" in methods:
            cutters["auto"] = lambda img, cut: auto_cut(img, orient, 0.5)
        for name, cells in (("own", [(img, cut) for _i, _f, img, cut in rest]),
                            ("shared", None)):
            if name not in methods:
                continue
            if cells is None:
                cells = []
                for gg in O.V_POOL:
                    rr, _ = O._pool(gg, ds)
                    cells += [(img, cut) for i, _f, img, cut in rr if i.split(":")[0] not in held]
            net = NpNet.from_torch(O._train_unet2(cells, orient, epochs=a.epochs))
            cutters[name] = (lambda n: lambda img, cut: prob_to_polyline2(predict_prob_np(n, img), orient))(net)
        if "comp" in methods:
            cells, used = comp_pool(ds, plan, fixed, held)
            print("  comp pool", used, flush=True)
            net = NpNet.from_torch(O._train_unet2(cells, orient, epochs=a.epochs))
            cutters["comp"] = (lambda n: lambda img, cut: prob_to_polyline2(predict_prob_np(n, img), orient))(net)
        if "prior" in methods:
            shp = mean_shape([cut for _i, _f, _img, cut in rest], orient)
            cutters["prior"] = lambda img, cut: prior_seam(img, shp, orient)
        if "tmpl" in methods:
            fx = [part_of(img, cut, orient, fixed) for _i, _f, img, cut in rest]
            mean_t = np.mean([p for p in fx if p is not None], axis=0)
            cutters["tmpl"] = lambda img, cut: tmpl_cut(img, mean_t, orient, fixed)
        bank = {}
        for _i, f, img, cut in rest:
            p = extract(img, cut)
            if p is not None:
                bank.setdefault(f, []).append(O.quantize(p).astype(np.float32) / 255.0)
        for i, form, img, cut in test:
            for name, f in cutters.items():
                pl = f(img, cut)
                x = extract(img, pl) if pl is not None else None
                best, m, _ = _choose_norm(x, bank, 0.0) if x is not None else (None, 0.0, {})
                rec[name].append((i, form, best if best in members else None, float(m), agree(img, pl, cut, orient)))
        print("fold", k, "done", flush=True)
    out = {}
    for name, rs in rec.items():
        right = [r for r in rs if r[2] == r[1]]
        wrong = [r for r in rs if r[2] is not None and r[2] != r[1]]
        th = max((r[3] for r in wrong), default=-1.0)
        cover = sum(1 for r in right if r[3] > th) / len(rs)
        out[name] = {"right": len(right), "wrong": len(wrong), "abstain": len(rs) - len(right) - len(wrong),
                     "zero_err_cover": round(cover, 3), "zero_err_margin": round(th, 4),
                     "seg_agree": round(float(np.mean([r[4] for r in rs])), 4),
                     "wrong_cells": [(r[0], r[1], r[2], round(r[3], 4)) for r in wrong]}
    print(json.dumps({"group": g, "cells": len(rows), "plan": plan.frame, "result": out}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
