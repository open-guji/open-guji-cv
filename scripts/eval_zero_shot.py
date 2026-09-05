# -*- coding: utf-8 -*-
"""零样本识别评测：字形库 unseen 档上，比较「整字 HOG 检索」与「拆字重排」。

## 量什么

`cache/glyph_bench` 的 unseen 档（≤2 样本的 1,022 字种）——模板从未见过这些字
的任何刻例，只能靠字体渲染 + 结构。指标 top-1 / top-5 / top-10，字表用整理本
4,636 字（生产口径），另报「字表里有没有这个字」的上限。

## 两个打分器

- **whole**：整字 HOG 余弦（现有 L1 字体模板路线，基线）；
- **parts**：先 whole 取 top-K，再按 IDS 结构把查询图与模板图**各自**沿结构
  边界切成两半，两半分别做 HOG 余弦后取均值，重排 top-K。
  直觉：刻本磨损/断墨是局部的，整字 HOG 一处坏全盘拉低；分部件比对，
  坏的那一半只拖累一半。⿰ 沿竖向墨谷切，⿱ 沿横向墨谷切，其余结构不切
  （退化为 whole）。

用法：
    python scripts/eval_zero_shot.py [--n 300] [--k 50] [--split unseen]
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

BENCH = Path("cache/glyph_bench")


def _split_point(binary: np.ndarray, axis: int, lo: float = 0.3, hi: float = 0.7) -> int:
    """沿 axis 找 [lo,hi] 区间内墨最少的一条线。axis=1 → 竖切（左右），0 → 横切（上下）。"""
    prof = binary.mean(axis=axis)          # axis=1: 每列? 注意：mean(axis=1) 是逐行
    n = len(prof)
    a, b = int(n * lo), int(n * hi)
    seg = prof[a:b]
    return a + int(np.argmin(seg)) if seg.size else n // 2


def _parts(binary: np.ndarray, struct: str) -> list[np.ndarray] | None:
    """按结构切两半；不支持的结构返回 None。"""
    h, w = binary.shape
    if struct.startswith("⿰") or struct.startswith("⿲"):
        x = _split_point(binary, axis=0)   # 逐列墨量 → 竖切
        return [binary[:, :x], binary[:, x:]]
    if struct.startswith("⿱") or struct.startswith("⿳"):
        y = _split_point(binary, axis=1)   # 逐行墨量 → 横切
        return [binary[:y, :], binary[y:, :]]
    return None


def _fit(img: np.ndarray, size: int = 64) -> np.ndarray:
    """半块图重新贴合到 size×size（保持比例、居中），让两半各自成为可比的样本。"""
    ys, xs = np.nonzero(img)
    if ys.size == 0:
        return np.zeros((size, size), np.uint8)
    img = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = img.shape
    s = (size - 8) / max(h, w)
    nh, nw = max(1, int(h * s)), max(1, int(w * s))
    r = cv2.resize(img.astype(np.uint8) * 255, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((size, size), np.uint8)
    y0, x0 = (size - nh) // 2, (size - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = (r > 127).astype(np.uint8)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--split", default="unseen")
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    from open_guji_cv.clustering.features import get_feature
    from open_guji_cv.clustering.font_candidates import (_font_files, book_charset,
                                                         candidates)
    from open_guji_cv.clustering.ids_guard import structure
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.synth import render_char

    items = [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()]
    items = [i for i in items if i["split"] == a.split]
    rng = random.Random(a.seed)
    rng.shuffle(items)
    items = items[:a.n]
    cs = tuple(book_charset(a.corpus))
    cs_set = set(cs)
    feat = get_feature("hog")
    fonts = _font_files()

    tmpl_cache: dict[str, np.ndarray | None] = {}

    def template(ch: str) -> np.ndarray | None:
        if ch in tmpl_cache:
            return tmpl_cache[ch]
        img = None
        for f in fonts:
            try:
                im = render_char(ch, f, size=64)
            except Exception:
                continue
            if im is not None and im.any():
                img = im.astype(np.uint8)
                break
        tmpl_cache[ch] = img
        return img

    def cos(u: np.ndarray, v: np.ndarray) -> float:
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        return float(u @ v / (nu * nv)) if nu and nv else 0.0

    def parts_score(q: np.ndarray, ch: str, whole: float) -> float:
        st = structure(ch)
        qp = _parts(q, st)
        t = template(ch)
        if qp is None or t is None:
            return whole
        tp = _parts(t, st)
        if tp is None:
            return whole
        s = []
        for x, y in zip(qp, tp):
            fx = feat.extract(_fit(x)[None, ...])[0]
            fy = feat.extract(_fit(y)[None, ...])[0]
            s.append(cos(fx, fy))
        return 0.5 * whole + 0.5 * float(np.mean(s))

    rk = {"whole": Counter(), "parts": Counter()}
    n = 0
    in_cs = 0
    for it in items:
        img = cv2.imread(it["png"], cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        q = normalize_patch(img)
        gold = it["char"]
        n += 1
        in_cs += gold in cs_set
        hits = candidates(q, cs, k=a.k)
        order_w = [h.char for h in hits]
        rescored = sorted(hits, key=lambda h: -parts_score(q, h.char, h.score))
        order_p = [h.char for h in rescored]
        for name, order in (("whole", order_w), ("parts", order_p)):
            r = order.index(gold) + 1 if gold in order else 999
            rk[name]["t1"] += r == 1
            rk[name]["t5"] += r <= 5
            rk[name]["t10"] += r <= 10
    print(f"split={a.split} n={n}  金标在字表内 {in_cs}/{n}={in_cs/n:.0%}（top-k 的上限）")
    for name in ("whole", "parts"):
        c = rk[name]
        print(f"  {name:6s} top1 {c['t1']/n:5.1%}  top5 {c['t5']/n:5.1%}  top10 {c['t10']/n:5.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
