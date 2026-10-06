"""a4：查询侧预处理变体 × 四庫库（库不动）重比对，量 top-1/top-5。

  python a4_rematch.py <patches.pkl> <out.jsonl> [variant ...] [--limit N]

变体（都只改「字块 → normalize_patch 之前/之后」，库侧 derived.norm 原样）：
  base      现役：normalize_patch(img)
  med5      先 3×… 中值滤波 5 去针孔毛刺
  down      先按字高缩到四庫尺度（×112/206 ≈0.55，INTER_AREA 灰度），再 normalize
  down_med  先中值 5 再缩
  close3    先闭运算 3×3（填针孔）
  dil1      normalize 后 64² 图膨胀 1px（补相对笔粗）
  med_dil   中值 5 + 64² 膨胀 1px
  down_med_dil 中值 5 + 缩 + 64² 膨胀 1px
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from a1_score_dist import rel  # noqa: E402

SIKU_SIZE = 112.0   # 四庫库字块字身中位（px，a3 实测）
QTW_SIZE = 206.0


def _med(img, k=5):
    return cv2.medianBlur(img, k)


def _down(img, f):
    h, w = img.shape
    return cv2.resize(img, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)


def _dil(n, px=1):
    return cv2.dilate(n, np.ones((2 * px + 1, 2 * px + 1), np.uint8))


def make_variants(scale: float):
    from open_guji_cv.clustering.normalize import normalize_patch as N
    close = lambda im: 255 - cv2.morphologyEx(255 - im, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return {
        "base": lambda im, p: N(im, isotropic=p),
        "med5": lambda im, p: N(_med(im), isotropic=p),
        "down": lambda im, p: N(_down(im, scale), isotropic=p),
        "down_med": lambda im, p: N(_down(_med(im), scale), isotropic=p),
        "close3": lambda im, p: N(close(im), isotropic=p),
        "dil1": lambda im, p: _dil(N(im, isotropic=p)),
        "med_dil": lambda im, p: _dil(N(_med(im), isotropic=p)),
        "down_med_dil": lambda im, p: _dil(N(_down(_med(im), scale), isotropic=p)),
        # ── 原分辨率上加粗（中值去针孔后按 r px 膨胀墨）──
        "thick1": lambda im, p: N(_thicken(_med(im), 1), isotropic=p),
        "thick2": lambda im, p: N(_thicken(_med(im), 2), isotropic=p),
        "thick3": lambda im, p: N(_thicken(_med(im), 3), isotropic=p),
        "thick_auto": lambda im, p: N(_thicken_to(_med(im), 0.065), isotropic=p),
        # ── 反向：把四庫字块仿成全唐文的样子（只对 vol03 有意义）──
        "sim_up": lambda im, p: N(_sim(im, thin=0, speck=0.0), isotropic=p),
        "sim_thin": lambda im, p: N(_sim(im, thin=3, speck=0.0), isotropic=p),
        "sim_speck": lambda im, p: N(_sim(im, thin=0, speck=0.25), isotropic=p),
        "sim_all": lambda im, p: N(_sim(im, thin=3, speck=0.25), isotropic=p),
    }


def _thicken(img, r: int):
    ink = (img < 128).astype(np.uint8)
    ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    return ((1 - ink) * 255).astype(np.uint8)


def _thicken_to(img, target_rel: float):
    """逐块估笔粗（距离变换×2 的中位，骨架上取），按需膨胀到 目标相对笔粗 × 字身。"""
    from metrics import stroke_width_dt
    ink = (img < 128).astype(np.uint8)
    ys, xs = np.nonzero(ink)
    if len(xs) < 20:
        return img
    size = max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1)
    sw = stroke_width_dt(ink) or 0
    r = int(round(max(0.0, target_rel * size - sw) / 2))
    return _thicken(img, min(r, 6)) if r else img


def _sim(img, thin: int, speck: float, seed: int = 0):
    """四庫字块 → 仿全唐文：按字身比放大（最近邻，保持双值）→ 腐蚀 thin px 让相对笔粗
    从 0.070 落到 ~0.043 → 墨内随机打针孔（比例 speck，按 3×3 团块），仿 JB2 毛刺。"""
    f = QTW_SIZE / SIKU_SIZE
    h, w = img.shape
    up = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_NEAREST)
    ink = (up < 128).astype(np.uint8)
    if thin:
        ink = cv2.erode(ink, np.ones((2 * thin + 1, 2 * thin + 1), np.uint8))
    if speck:
        rng = np.random.default_rng(seed)
        holes = (rng.random(ink.shape) < speck / 9).astype(np.uint8)
        holes = cv2.dilate(holes, np.ones((3, 3), np.uint8))
        ink = ink & (1 - holes)
    return ((1 - ink) * 255).astype(np.uint8)


def load_matcher():
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    m, chars = load_matcher_from_db(GlyphDB(os.environ["GUJI_GLYPH_DB"]), knn_k=10)
    return m, chars


def main():
    argv = sys.argv[1:]
    if "--limit" in argv:
        i = argv.index("--limit"); argv = argv[:i] + argv[i + 2:]
    args = argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    pkl, out = args[0], args[1]
    names = args[2:] or ["base"]
    recs = pickle.load(open(pkl, "rb"))
    if limit:
        recs = recs[:limit]
    matcher, lib_chars = load_matcher()
    t0 = time.time()
    with open(out, "w", encoding="utf-8") as fo:
        for r in recs:
            scale = SIKU_SIZE / QTW_SIZE if r["book"] != "vol03" else 1.0
            V = make_variants(scale)
            row = {"id": r["id"], "book": r["book"], "truth": r["truth"],
                   "in_lib": any(rel(r["truth"], c) for c in [r["truth"]]) and r["truth"] in lib_chars}
            for nm in names:
                norm = V[nm](r["img"], bool(r.get("punct")))
                m = matcher.match(norm, exclude_id=r["id"])
                cands = [(c, round(float(v), 4)) for c, v in m.candidates[:10]]
                rk = next((i + 1 for i, (c, _) in enumerate(cands) if rel(c, r["truth"])), 11)
                row[nm] = {"v": m.verdict, "cov": round(float(m.cov), 4), "wmax": round(float(m.wmax), 2),
                           "rank": rk, "top": cands[0][0] if cands else None,
                           "tcov": next((v for c, v in cands if rel(c, r["truth"])), None),
                           "ink": round(float(norm.mean()), 4)}
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(recs)} recs × {len(names)} variants in {time.time()-t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
