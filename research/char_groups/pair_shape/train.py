"""训练书级「两字」刻形模型（`groups/pair_shape.py`）。

用法：python train.py <工作区> <两字，如 之矣> <册,册,…> [--products <产物根>] [--out model.json]
数据：各册 seed_admit 产物里已放行（admit，非 coord_fallback）的这两个字格＋字块缓存 `cache/<册>/char_patch/`。
按册留出：每册用其余各册训的模型判，报 对／错／弃权；guard＝留出里正确格最近 5 个平均距离的 99.5 分位，thr 默认 1.0。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

from open_guji_cv.groups.rr_shape import features

PCA_K = 40


def load_cells(ws, products, vols, chars):
    cache = Path(ws) / "cache"
    data = {}
    for v in vols:
        for f in sorted(glob.glob(f"{products}/{v}/seed_admit/p*.json")):
            d = json.load(open(f, encoding="utf-8"))["seed_admit"]
            for col in d["columns"]:
                for c in col["chars"]:
                    if c["char"] not in chars or not c.get("admit") or c.get("channel") == "coord_fallback":
                        continue
                    _, p, cc, s = c["id"].split(":")
                    q = cache / v / "char_patch" / f"p{int(p):04d}c{int(cc):02d}s{s}.png"
                    if not q.exists():
                        continue
                    import cv2
                    g = cv2.imread(str(q), 0)
                    x, _ = features(g)
                    if x is not None:
                        data.setdefault(v, []).append((x, c["char"], c["id"]))
    return data


def fit(F, y):
    from sklearn.linear_model import LogisticRegression
    mean, scale = F.mean(0), F.std(0) + 1e-6
    m = LogisticRegression(C=0.1, max_iter=3000, class_weight="balanced").fit((F - mean) / scale, y)
    pm = F.mean(0)
    _, _, vt = np.linalg.svd(F - pm, full_matrices=False)
    pc = vt[:PCA_K]
    return {"mean": mean, "scale": scale, "coef": m.coef_[0], "intercept": float(m.intercept_[0]),
            "pca_mean": pm, "pca": pc, "bank": (F - pm) @ pc.T}


def nn5(model, f):
    z = (f - model["pca_mean"]) @ model["pca"].T
    return float(np.sort(np.sqrt(((model["bank"] - z) ** 2).sum(1)))[:5].mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws"); ap.add_argument("chars"); ap.add_argument("vols")
    ap.add_argument("--products", default=None); ap.add_argument("--out", default="pair_shape.json")
    ap.add_argument("--exclude", default="", help="看图确认放行错了的格号，逗号分隔（训练前剔除）")
    a = ap.parse_args()
    ch = list(a.chars)
    assert len(ch) == 2
    vols = a.vols.split(",")
    data = load_cells(a.ws, a.products or os.environ["GUJI_PRODUCTS_DIR"], vols, ch)
    bad = set(filter(None, a.exclude.split(',')))
    data = {v: [r for r in rs if r[2] not in bad] for v, rs in data.items()}
    ok = err = ab = 0
    nns, errs = [], []
    thr = float(os.environ.get('PS_THR', 1.0))
    for te in data:
        tr = [v for v in data if v != te]
        F = np.array([r[0] for v in tr for r in data[v]]); y = np.array([r[1] == ch[1] for v in tr for r in data[v]])
        m = fit(F, y)
        for x, c, i in data[te]:
            nn = nn5(m, x)
            s = float(((x - m["mean"]) / m["scale"]) @ m["coef"] + m["intercept"])
            if abs(s) < thr:
                ab += 1; continue
            pred = ch[1] if s > 0 else ch[0]
            if pred == c:
                ok += 1; nns.append(nn)
            else:
                err += 1; errs.append((i, c, round(s, 2), round(nn, 3)))
    guard = float(np.percentile(nns, 99.5))
    print('nn 分位 50/90/97/99/99.5:', np.round(np.percentile(nns, [50, 90, 97, 99, 99.5]), 3))
    print(f"按册留出：对 {ok} 错 {err} 弃权 {ab}（thr={thr}，guard={guard:.3f}）错例 {errs}")
    F = np.array([r[0] for v in data for r in data[v]]); y = np.array([r[1] == ch[1] for v in data for r in data[v]])
    m = fit(F, y)
    out = {"schema": "pair_shape/1", "chars": ch, "thr": thr, "guard": guard,
           "note": f"{vols} 已放行格 {len(F)}；按册留出 对{ok} 错{err} 弃{ab}"}
    for k, v in m.items():
        out[k] = np.asarray(v).tolist() if not isinstance(v, float) else v
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("写出", a.out)


if __name__ == "__main__":
    main()
