"""字形判别台（M7，2026-10-22）：每组只给数据，不给参数；候选方法按册留出**嵌套**选，报外层册的真实覆盖。

候选（`configs`）：特征 HOG × 尺寸 32／48 × 区域（整字、0.25 网格上宽高 ≥0.5 的子框、按训练册两形平均图之差自动取的「判别框」）
× 识别器（岭回归，二类或一对多；最近邻）。
嵌套按册留出：外层留一册当测试；内层在其余册上再按册留一，给每个候选算「0 错门槛（错例最大 margin）与门槛上的覆盖」，
取内层覆盖最高的候选和它的门槛，用全部训练册拟合，判外层册。外层册不参与任何选择，所以报出来的覆盖与错数不偏乐观
（`research/m7/glyph_expand/scan_region.py` 是在同批数据上选区域的，偏乐观）。
数据：数据集 `labels/unified.jsonl` 的人裁刻形（kind=shape、status=ok）＋ `export_crops.py` 导出的字块图。

用法：python bench.py <dataset char-groups 根> <字块图目录> <组 id|all> [--min-form 8] [--json out.json]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from open_guji_cv.groups import ids_whole  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS  # noqa: E402

_G = (0.0, 0.25, 0.5)
_H = (0.5, 0.75, 1.0)
GRID = [(x0, x1, y0, y1) for x0, x1 in itertools.product(_G, _H) for y0, y1 in itertools.product(_G, _H)
        if x1 - x0 >= 0.5 and y1 - y0 >= 0.5]
SIZES = (32, 48)


def glyph_store_human(gs: Path, members: set) -> dict:
    """中心库字形库（`guji db pull` 后的 `output/glyph_store`）里 label_status=human 的实例 → {格 id: (字, 图路径)}。"""
    out = {}
    for f in sorted(gs.glob("instances/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("label_status") != "human" or r.get("label") not in members:
                continue
            iid = r["instance_id"]
            for stem in (iid.replace(":", "_"), "v1_" + iid.replace(":", "_")):
                if (gs / "patches" / f"{stem}.png").exists():
                    out.setdefault(iid.split(":", 1)[1] if iid.startswith(("v1:", "v2:")) else iid, (r["label"], gs / "patches" / f"{stem}.png"))
                    break
    return out


def load(root: Path, crops: Path, members: set, extra: list[Path] = (), gs: Path | None = None, only: bool = False):
    """→ [(字, 灰度, 册, 格 id)]。数据集人裁为主；给了字形库 `gs` 再并入其中 human 实例（数据集没有的格）。
    同一格多条且字不一致的整格丢弃。`only`：只用 `crops`／`extra` 里的图（如线上同款 char_patch），不并入数据集自带的字块图。"""
    paths = {}
    for d in (crops, *extra):
        for f in Path(d).glob("*.png"):
            paths.setdefault(f.stem, f)
    for f in ([] if only else list(root.glob("variant/*/crops/*.png")) + list(root.glob("*/crops/*.png"))):
        paths.setdefault(f.stem, f)
    forms = defaultdict(set)
    for line in open(root / "labels" / "unified.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["kind"] == "shape" and r["status"] == "ok" and r.get("form") in members:
            forms[r["id"]].add(r["form"])
    if gs is not None:
        for cid, (form, p) in glyph_store_human(gs, members).items():
            if cid not in forms:
                paths.setdefault(cid.replace(":", "_"), p)
            forms[cid].add(form)
    out = []
    for cid, fs in sorted(forms.items()):
        p = paths.get(cid.replace(":", "_"))
        if len(fs) != 1 or p is None:
            continue
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            out.append((next(iter(fs)), g, cid.split(":")[0], cid))
    return out


def diff_box(imgs: np.ndarray, labels: np.ndarray):
    """两形（多形取两两最大）平均墨迹图之差最集中的网格子框：框内平均差 ÷ 全图平均差最大，面积 ≥1/4。"""
    means = [imgs[labels == c].mean(0) for c in np.unique(labels)]
    d = np.zeros_like(means[0])
    for a, b in itertools.combinations(means, 2):
        d = np.maximum(d, np.abs(a - b))
    n = d.shape[0]
    best, box = -1.0, (0.0, 1.0, 0.0, 1.0)
    for x0, x1, y0, y1 in GRID:
        v = d[int(y0 * n):int(y1 * n), int(x0 * n):int(x1 * n)].mean()
        if v > best:
            best, box = v, (x0, x1, y0, y1)
    return box


class Feats:
    """按 (尺寸, 区域) 缓存全部格的 HOG 特征。"""

    def __init__(self, cells):
        self.cells = cells
        self.norm = {s: [ids_whole.norm(np.asarray(g), s) for _f, g, _b, _i in cells] for s in SIZES}
        self.ok = np.array([all(self.norm[s][k] is not None for s in SIZES) for k in range(len(cells))])
        self._c = {}

    def get(self, size, region):
        k = (size, region)
        if k not in self._c:
            fs = [ids_whole.feature(x, "hog", region) if x is not None else None for x in self.norm[size]]
            dim = next(len(f) for f in fs if f is not None)
            self._c[k] = np.array([f if f is not None else np.zeros(dim) for f in fs], np.float64)
        return self._c[k]


def fit_predict(x_tr, y_tr, x_te, names, clf, lam=1.0):
    """→ (预测类下标, margin)。ridge：对偶形式（样本少、维数高）；knn：余弦最近邻，margin＝最近他类 − 最近本类 的距离差。"""
    if clf == "knn":
        a = x_tr / (np.linalg.norm(x_tr, axis=1, keepdims=True) + 1e-9)
        b = x_te / (np.linalg.norm(x_te, axis=1, keepdims=True) + 1e-9)
        dist = 1.0 - b @ a.T
        per = np.stack([dist[:, y_tr == c].min(1) if (y_tr == c).any() else np.full(len(b), 9.0)
                        for c in range(len(names))], 1)
        o = np.argsort(per, 1)
        return o[:, 0], per[np.arange(len(b)), o[:, 1]] - per[np.arange(len(b)), o[:, 0]]
    xa = np.c_[x_tr, np.ones(len(x_tr))]
    xb = np.c_[x_te, np.ones(len(x_te))]
    t = np.where(np.arange(len(names))[None, :] == y_tr[:, None], 1.0, -1.0)
    alpha = np.linalg.solve(xa @ xa.T + lam * np.eye(len(xa)), t)
    sc = xb @ (xa.T @ alpha)
    if len(names) == 2:
        d = sc[:, 1] - sc[:, 0]
        return (d > 0).astype(int), np.abs(d) / 2
    o = np.argsort(-sc, 1)
    return o[:, 0], sc[np.arange(len(sc)), o[:, 0]] - sc[np.arange(len(sc)), o[:, 1]]


def loo_books(F, idx, y, books, cfg, names):
    """在 idx 这些格上按册留一 → [(真, 判, margin)]。"""
    size, region, clf = cfg
    x = F.get(size, region)
    res = []
    for b in sorted(set(books[idx])):
        te = idx[books[idx] == b]
        tr = idx[books[idx] != b]
        if len(set(y[tr])) < len(names):
            continue
        p, m = fit_predict(x[tr], y[tr], x[te], names, clf)
        res += list(zip(y[te], p, m))
    return res


def zero_err(res):
    """→ (门槛, 门槛上对的格数)。门槛＝错例最大 margin（无错 → 0）。"""
    w = [m for t, p, m in res if p != t]
    thr = max(w) + 1e-6 if w else 0.0
    return thr, sum(1 for t, p, m in res if p == t and m >= thr)


def configs(F, idx, y, names):
    box = diff_box(np.array([F.norm[48][k] for k in idx]), y[idx])
    regs = [(0.0, 1.0, 0.0, 1.0), box] + [r for r in GRID if r not in ((0.0, 1.0, 0.0, 1.0), box)]
    return [(s, r, c) for s in SIZES for r in regs for c in ("ridge", "knn")], box


def bench(cells, min_books=3):
    keep = [k for k in range(len(cells))]
    F = Feats(cells)
    keep = np.array([k for k in keep if F.ok[k]])
    names = sorted({cells[k][0] for k in keep})
    y = np.array([names.index(c[0]) for c in cells])
    books = np.array([c[2] for c in cells])
    vols = sorted(set(books[keep]))
    if len(names) < 2 or len(vols) < min_books:
        return {"skip": "形或册不够", "forms": dict(Counter(c[0] for c in cells))}
    outer, picks = [], []
    for b in vols:
        te = keep[books[keep] == b]
        tr = keep[books[keep] != b]
        if len(set(y[tr])) < len(names) or not len(te):
            continue
        best = None
        cfgs, box = configs(F, tr, y, names)
        for cfg in cfgs:
            thr, ok = zero_err(loo_books(F, tr, y, books, cfg, names))
            if best is None or ok > best[0]:
                best = (ok, cfg, thr)
        _ok, cfg, thr = best
        x = F.get(cfg[0], cfg[1])
        p, m = fit_predict(x[tr], y[tr], x[te], names, cfg[2])
        picks.append((b, cfg, round(thr, 3)))
        for k, pi, mi in zip(te, p, m):
            outer.append((cells[k][3], names[y[k]], names[pi] if mi >= thr else None, float(mi)))
    right = sum(1 for _i, t, p, _m in outer if p == t)
    wrong = [(i, t, p, round(m, 3)) for i, t, p, m in outer if p is not None and p != t]
    per = Counter(t for _i, t, p, _m in outer if p == t)
    tot = Counter(t for _i, t, _p, _m in outer)
    whole_fixed = zero_err(loo_books(F, keep, y, books, (32, (0.0, 1.0, 0.0, 1.0), "ridge"), names))
    return {"cells": len(outer), "forms": dict(tot), "right": right, "wrong": len(wrong), "abstain": len(outer) - right - len(wrong),
            "cover": round(right / max(len(outer), 1), 3), "per_form": {f: f"{per[f]}/{tot[f]}" for f in sorted(tot)},
            "wrong_cells": wrong, "picks": Counter(f"{c[2]} {c[0]} {c[1]}" for _b, c, _t in picks).most_common(4),
            "baseline_whole32_ridge_sameset": f"{whole_fixed[1]}/{len(keep)}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("crops", type=Path)
    ap.add_argument("group")
    ap.add_argument("--min-form", type=int, default=8)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--only-crops", action="store_true", help="只用给定目录里的字块图（线上同款 char_patch），不并入数据集自带图")
    ap.add_argument("--glyph-store", type=Path, help="并入中心库字形库 human 实例（guji db pull 后的 output/glyph_store）")
    a = ap.parse_args()
    gids = list(FLOW_GROUPS) if a.group == "all" else a.group.split(",")
    out = {}
    for g in gids:
        mem = set(FLOW_GROUPS[g].members)
        cells = load(a.root, a.crops, mem, gs=a.glyph_store, only=a.only_crops)
        cnt = Counter(c[0] for c in cells)
        forms = [f for f, n in cnt.items() if n >= a.min_form]
        if len(forms) < 2:
            out[g] = {"skip": f"每形 ≥{a.min_form} 的不到两形", "forms": dict(cnt)}
        else:
            out[g] = bench([c for c in cells if c[0] in forms])
        print(g, "".join(sorted(mem)), json.dumps(out[g], ensure_ascii=False), flush=True)
    if a.json:
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
