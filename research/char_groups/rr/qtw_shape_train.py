"""入人八 书级刻形判法训练与按册留出（全唐文，A24 线 3，2026-11-02）→ `config/groups/rr_shape.json`（`groups.rr_shape`）。

    python research/char_groups/rr/qtw_shape_train.py <cells.json> <字块目录> <输出.json> [--exclude id,id]

- `cells.json`：[{id, vol, admit, char}]，已放行且 char∈人入八 的格当标签（放行字当标签，见方法论 2.7；
  看图确认放错的格用 --exclude 去掉，如 06:117:3:1／06:117:4:8 刻的是「尺」）。
- 字块目录：`<id 把 : 换成 _>.png` 灰度字块（原图按 cell_shrink bbox_page 裁，或管线 char_patch）。
- 按册留出：每册用其余各册训的模型判，报 对／错／弃权；门槛 `thr`（LR 决策值）与护栏 `guard`（PCA 最近 5 个平均距离）
  取留出里正确格的分布定：guard＝99.5 分位，thr＝1.0（留出错例都在 1 以内时）。
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.groups import rr_shape  # noqa: E402

PARAMS = {"ba_rtop_max": 0.05, "ba_ltop_min": 0.2, "ba_rh_min": 0.8, "ba_lh_min": 0.5, "ba_ratio_min": 0.3,
          "ren_rtop_min": 0.3}
PCA_K = 40
C = 0.01


def lr_fit(X, y, c=C, iters=3000):
    """标准化＋L2 逻辑回归（梯度下降，免 sklearn 依赖）。→ mean, scale, coef, intercept。"""
    mu, sd = X.mean(0), np.maximum(X.std(0), 1e-3)   # 下限：导出时四舍五入不能把常数维的 scale 变成 0
    Z = (X - mu) / sd
    w = np.zeros(Z.shape[1]); b = 0.0
    lam = 1.0 / (c * len(y))
    lr = 0.5
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = Z.T @ (p - y) / len(y) + lam * w
        w -= lr * g; b -= lr * float((p - y).mean())
    return mu, sd, w, b


def pca_fit(X, k):
    m = X.mean(0)
    _, _, vt = np.linalg.svd(X - m, full_matrices=False)
    return m, vt[:k]


def build(F, G, lab, tr):
    """在 tr（下标）上训 → 模型 dict（未定 thr/guard）。"""
    ri = [i for i in tr if lab[i] in "人入" and G[i]["n"] >= 1 and (G[i]["n"] == 1 or rr_shape.is_broken_ren(G[i], PARAMS))]
    mu, sd, w, b = lr_fit(F[ri], np.array([lab[i] == "入" for i in ri], float))
    pm, pc = pca_fit(F[tr], PCA_K)
    return {"schema": rr_shape.SCHEMA, "mean": mu, "scale": sd, "coef": w, "intercept": b,
            "pca_mean": pm, "pca": pc, "bank": (F[tr] - pm) @ pc.T, "params": PARAMS, "thr": 1.0, "guard": 1e9}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells"); ap.add_argument("patches"); ap.add_argument("out")
    ap.add_argument("--exclude", default="06:117:3:1,06:117:4:8")
    a = ap.parse_args()
    import cv2
    ex = set(a.exclude.split(","))
    cells = [c for c in json.load(open(a.cells, encoding="utf-8"))
             if c["admit"] and c["char"] in "人入八" and c["id"] not in ex]
    F, G, lab, vol, ids = [], [], [], [], []
    for c in cells:
        g = cv2.imread(str(Path(a.patches) / (c["id"].replace(":", "_") + ".png")), cv2.IMREAD_GRAYSCALE)
        f, geo = rr_shape.features(g)
        if f is None:
            continue
        F.append(f); G.append(geo); lab.append(c["char"]); vol.append(c["vol"]); ids.append(c["id"])
    F = np.array(F); vol = np.array(vol)
    res, nns = [], []
    for v in sorted(set(vol)):
        te = np.where(vol == v)[0]; tr = np.where(vol != v)[0]
        m = build(F, G, lab, tr)
        for i in te:
            z = (F[i] - m["pca_mean"]) @ m["pca"].T
            nn = float(np.sort(np.sqrt(((m["bank"] - z) ** 2).sum(1)))[:5].mean())
            if rr_shape.is_ba(G[i], PARAMS):
                ch, s = "八", None
            elif G[i]["n"] >= 2 and not rr_shape.is_broken_ren(G[i], PARAMS):
                ch, s = None, None
            else:
                s = float(((F[i] - m["mean"]) / m["scale"]) @ m["coef"] + m["intercept"])
                ch = "入" if s > 0 else "人"
            res.append((ids[i], lab[i], ch, s, nn))
            if ch == lab[i]:
                nns.append(nn)
    guard = float(np.percentile(nns, 99.5))
    thr = 1.0
    ok = err = ab = 0
    errs = []
    for i, y, ch, s, nn in res:
        if ch is None or nn > guard or (s is not None and abs(s) < thr):
            ab += 1
        elif ch == y:
            ok += 1
        else:
            err += 1; errs.append((i, y, ch, s, round(nn, 2)))
    print(f"按册留出：对 {ok}  错 {err}  弃权 {ab}  （guard={guard:.3f} thr={thr}）")
    for e in errs:
        print("  错", e)
    m = build(F, G, lab, np.arange(len(F)))
    m.update(thr=thr, guard=guard, note=f"全唐文 04–15 已放行格 {len(F)}；按册留出 对{ok} 错{err} 弃{ab}")
    m = {k: (v.round(5).tolist() if isinstance(v, np.ndarray) else v) for k, v in m.items()}
    Path(a.out).write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("写", a.out, f"{Path(a.out).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
