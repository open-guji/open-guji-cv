"""训练书级「两字」刻形模型 `pair_shape/2`（墨量图＋组外判别；全唐文 大太／王玉／還遺，2026-11-07）。

用法：
  python train_pix.py <产物根> <原图根> <两字> --bg <组外形近字> [--vols 005,006,…] [--exclude 格,格] [--out m.json]

- 产物根：`<产物根>/<册>/{seed_admit,cell_shrink}/pNNNN.json`；原图根：`<原图根>/<册>/<页>.png`（`guji source pull --to`）。
- 标签：各册 seed_admit 已放行（非 coord_fallback）的这两字格；组外：已放行的 --bg 各字，每字最多 --bg-max 格。
- 字块：按 cell_shrink `bbox_page` 从原图裁（x 从右量，左＝W−x），外扩 4px；管线里推理用 `char_patch`，
  两者都先过 `pair_shape.pix_ink` 取主笔画紧框，框外差异不进特征。
- 训练：32×32 墨量图，框边随机抖 ±6% 各 4 份；两字 LR（C=0.05，平衡类权）＋「本组 vs 组外」LR。
- 按册留出：每册用其余各册训，报 给字／错／弃权、组外字漏过护栏数、错例格号（多为原放行标错，看图后 --exclude 再训）。
HOG（`pair_shape/1`）在点画差别上不行：全唐文 大太 留出错 278、王玉 183；本法 大太 错 1、王玉 0、還遺 0。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
from pathlib import Path

import numpy as np

from open_guji_cv.groups.pair_shape import SCHEMA_PIX, pix_features, pix_ink

SIZE = 32


def iter_cells(products: str, raw: str, vols, want):
    """→ (格号, 字, 墨图)。want(rec) 决定要不要。"""
    import cv2
    for v in vols:
        for f in sorted(glob.glob(f"{products}/{v}/seed_admit/p*.json")):
            pn = os.path.basename(f)
            sa = json.load(open(f, encoding="utf-8"))["seed_admit"]
            recs = [r for c in sa["columns"] for r in c["chars"] if want(r)]
            if not recs:
                continue
            cs = json.load(open(f"{products}/{v}/cell_shrink/{pn}", encoding="utf-8"))["char_index"]
            bb = {x["id"]: x.get("bbox_page") for c in cs["columns"] for x in c["chars"]}
            img = cv2.imread(f"{raw}/{v}/{int(pn[1:5])}.png", cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            W = img.shape[1]
            for r in recs:
                b = bb.get(r["id"])
                if not b:
                    continue
                x0, y0, x1, y1 = b
                g = img[max(0, int(y0) - 4):int(y1) + 4, max(0, int(W - x1) - 4):int(W - x0) + 4]
                ink = pix_ink(g)
                if ink is not None and min(ink.shape) >= 6:
                    yield r["id"], r["char"], ink


def jitter(ink, rng, n=4):
    H, W = ink.shape
    out = []
    for _ in range(n):
        dx0, dx1, dy0, dy1 = (rng.uniform(-.06, .06, 4) * [W, W, H, H]).astype(int)
        k = ink[max(0, dy0):H - max(0, dy1), max(0, dx0):W - max(0, dx1)]
        k = np.pad(k, ((max(0, -dy0), max(0, -dy1)), (max(0, -dx0), max(0, -dx1))))
        out.append(pix_features(k, SIZE))
    return out


def fit(inks, y, seed=0):
    from sklearn.linear_model import LogisticRegression
    rng = np.random.default_rng(seed)
    X = np.array([pix_features(k, SIZE) for k in inks])
    A = [a for k in inks for a in jitter(k, rng)]
    Xt = np.vstack([X, np.array(A)])
    yt = np.concatenate([y, np.repeat(y, 4)])
    mu, sd = Xt.mean(0), Xt.std(0) + 1e-3
    m = LogisticRegression(C=0.05, max_iter=4000, class_weight="balanced").fit((Xt - mu) / sd, yt)
    return {"mu": mu, "sd": sd, "coef": m.coef_[0], "b": float(m.intercept_[0])}


def lr(part, x):
    return float(((x - part["mu"]) / part["sd"]) @ part["coef"] + part["b"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("products"); ap.add_argument("raw"); ap.add_argument("chars")
    ap.add_argument("--bg", required=True, help="组外形近字（如 天夫犬丈夭失尤木本）")
    ap.add_argument("--bg-max", type=int, default=200)
    ap.add_argument("--vols", default="")
    ap.add_argument("--exclude", default="", help="看图确认放行标错的格号，逗号分隔（训练、留出都剔除）")
    ap.add_argument("--thr", type=float, default=2.0)
    ap.add_argument("--other-thr", type=float, default=-2.0)
    ap.add_argument("--veto-thr", type=float, default=6.0)
    ap.add_argument("--out", default="pair_shape.json")
    a = ap.parse_args()
    ch = list(a.chars)
    assert len(ch) == 2
    vols = a.vols.split(",") if a.vols else sorted(d for d in os.listdir(a.products) if d.isdigit())
    bad = set(filter(None, a.exclude.split(",")))
    ok_rec = lambda r: r.get("admit") and r.get("channel") != "coord_fallback" and r["id"] not in bad  # noqa: E731
    cells = list(iter_cells(a.products, a.raw, vols, lambda r: ok_rec(r) and r.get("char") in ch))
    cnt = collections.Counter()

    def want_bg(r):
        if ok_rec(r) and r.get("char") in a.bg and cnt[r["char"]] < a.bg_max:
            cnt[r["char"]] += 1
            return True
        return False
    bgs = list(iter_cells(a.products, a.raw, vols, want_bg))
    y = np.array([ch.index(c) for _, c, _ in cells])
    vol = np.array([i.split(":")[0] for i, _, _ in cells])
    bvol = np.array([i.split(":")[0] for i, _, _ in bgs])
    give = err = ab = leak = 0
    errs = []
    for v in sorted(set(vol)):
        te, bte = vol == v, bvol == v
        tr = [cells[i][2] for i in np.nonzero(~te)[0]]
        ab_m = fit(tr, y[~te])
        ot_m = fit(tr + [bgs[i][2] for i in np.nonzero(~bte)[0]],
                   np.array([0] * len(tr) + [1] * int((~bte).sum())), seed=1)
        for i in np.nonzero(te)[0]:
            x = pix_features(cells[i][2], SIZE)
            s, o = lr(ab_m, x), lr(ot_m, x)
            if abs(s) < a.thr or o >= a.other_thr:
                ab += 1
            elif (s > 0) == bool(y[i]):
                give += 1
            else:
                give += 1; err += 1; errs.append((cells[i][0], cells[i][1], round(s, 2)))
        for i in np.nonzero(bte)[0]:
            x = pix_features(bgs[i][2], SIZE)
            if abs(lr(ab_m, x)) >= a.thr and lr(ot_m, x) < a.other_thr:
                leak += 1
    note = (f"{''.join(ch)} 已放行 {len(cells)} 格（{dict(collections.Counter(c for _, c, _ in cells))}），组外 {len(bgs)} 格；"
            f"按册留出 给字 {give} 错 {err} 弃权 {ab}，组外漏 {leak}；剔除 {sorted(bad)}")
    print(note)
    print("错例：", errs)
    inks = [k for _, _, k in cells]
    ab_m = fit(inks, y)
    ot_m = fit(inks + [k for _, _, k in bgs], np.array([0] * len(inks) + [1] * len(bgs)), seed=1)
    tolist = lambda d: {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in d.items()}  # noqa: E731
    out = {"schema": SCHEMA_PIX, "chars": ch, "size": SIZE, "thr": a.thr, "other_thr": a.other_thr, "veto_thr": a.veto_thr,
           "bg": a.bg, "ab": tolist(ab_m), "other": tolist(ot_m), "note": note}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("写出", a.out)


if __name__ == "__main__":
    main()
