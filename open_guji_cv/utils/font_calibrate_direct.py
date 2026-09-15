# -*- coding: utf-8 -*-
"""字体判定·直接比对（不经库）：先把字体渲染加粗到书的笔宽，再量字形相似度。

`font_calibrate.score_fonts` 走库检索，模板是 `glyph-db import-font` 存进库的原样渲染。
北行日錄实测（2026-09-15）那条路的排名与**笔宽严格同序**：书上字块归一到 64px 后笔画
5.5px，SimSun / I.Ming / Jigmo 3.8px 排前三，中华书局宋体 / 細明體 / Noto 只有 2.7px 垫底
——分数主要在量粗细差，不是字形差（匹配栈 2026-08-24 起不做笔宽归一，那是给刻本定的）。
这里每套字体先按书的笔宽自动挑一个 PIL `stroke_width` 加粗，再 HOG 粗排 + elastic 精验，
量法与库检索一致，只是模板换成了加粗后的渲染。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from .font_calibrate import FontScore, _pct, patch_path


def stroke_width_px(norm01: np.ndarray) -> float:
    """归一二值图（64×64 {0,1}）的笔画宽度估计：墨像素距离变换值的 p90 × 2。"""
    m = (norm01 > 0).astype(np.uint8)
    if m.sum() == 0:
        return 0.0
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    return 2.0 * float(np.percentile(dt[m > 0], 90))


def calibrate_stroke(font_paths: list[Path], chars: list[str], target_w: float,
                     candidates=(0, 1, 2, 3, 4, 5, 6, 8)) -> tuple[int, float]:
    """挑一个 PIL stroke_width，让这套字体渲染后归一图的笔宽中位最接近 target_w。"""
    from ..clustering.font_glyphs import FontRenderer
    from ..clustering.normalize import normalize_patch
    best_sw, best_gap, best_w = 0, float("inf"), 0.0
    for sw in candidates:
        r = FontRenderer(font_paths, stroke_width=sw)
        ws = []
        for ch in chars:
            im = r.render(ch)
            if im is not None:
                ws.append(stroke_width_px(normalize_patch(im)))
        if not ws:
            continue
        med = float(np.median(ws))
        if abs(med - target_w) < best_gap:
            best_sw, best_gap, best_w = sw, abs(med - target_w), med
    return best_sw, best_w


def score_fonts_direct(book_id: str, labels: list[dict], cache_root: Path, fonts: list,
                       charset: list[str], *, k: int = 5, strokes: dict[str, int] | None = None,
                       match_stroke: bool = True, norm_stroke: int | None = None,
                       log=print) -> list[FontScore]:
    """每套字体按 charset 渲染成模板（可按书的笔宽加粗），HOG 粗排 + elastic 精验。
    `fonts` 是 `font_glyphs.FontSpec` 列表；`strokes` 显式给每套的加粗值，不给且
    `match_stroke=True` 就按书的笔宽自动标定。

    `norm_stroke`：两边都做笔宽归一（`normalize.stroke_normalize`：骨架化再统一膨胀到这个
    宽度）。**加粗到书的笔宽那条路是饱和的**（2026-09-15 实测：七套字体正确/错误命中 cov 都
    0.998～1.000，同字闸 same 判 644/675）——64px 图上 5px 宽的笔画，差一笔的形近字在软覆盖
    下也几乎全覆盖；细到 3px 再比，看的才是字形。"""
    from ..clustering.canonical import to_canonical
    from ..clustering.features import HogFeature
    from ..clustering.font_glyphs import FontRenderer
    from ..clustering.normalize import normalize_patch
    from ..clustering.verify import verify_pair_elastic

    def norm(img):
        return normalize_patch(img, stroke_width=norm_stroke)

    hog = HogFeature()
    queries: list[tuple[dict, np.ndarray]] = []
    for d in labels:
        g = cv2.imread(str(patch_path(cache_root, book_id, d)), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            queries.append((d, norm(to_canonical(g))))
    book_w = float(np.median([stroke_width_px(n) for _, n in queries]))
    log(f"[calibrate-font/direct] 查询字位 {len(queries)}，书的笔宽 {book_w:.2f}px（64px 归一图）"
        f"{f'，两边笔宽归一到 {norm_stroke}px' if norm_stroke else ''}")
    qF = hog.extract(np.stack([n for _, n in queries]))
    out: list[FontScore] = []
    for spec in fonts:
        paths = [Path(p) for p in spec.font_paths]
        if strokes and spec.edition_tag in strokes:
            sw, meas = strokes[spec.edition_tag], float("nan")
        elif match_stroke:
            sw, meas = calibrate_stroke(paths, [d["char"] for d, _ in queries[:40]], book_w)
        else:
            sw, meas = 0, float("nan")
        r = FontRenderer(paths, stroke_width=sw)
        t_chars, t_norms = [], []
        for ch in charset:
            im = r.render(ch)
            if im is None:
                continue
            t_chars.append(ch)
            t_norms.append(norm(im))
        tF = hog.extract(np.stack(t_norms))
        has = set(t_chars)
        r1 = r5 = covered = n_same = 0
        cov_ok: list[float] = []
        cov_wrong: list[float] = []
        conf: dict[str, int] = defaultdict(int)
        for (d, qn), qf in zip(queries, qF):
            ch = d["char"]
            if ch not in has:
                continue
            covered += 1
            sims = tF @ qf
            top = np.argsort(-sims)[:k]
            scored = []
            for j in top:
                v = verify_pair_elastic(qn, t_norms[int(j)])
                scored.append((float(v.f1), t_chars[int(j)], v.verdict))
            scored.sort(key=lambda t: -t[0])
            ranks = [c for _, c, _ in scored]
            if scored[0][2] == "same":
                n_same += 1
            if ranks[0] == ch:
                r1 += 1
                cov_ok.append(scored[0][0])
            else:
                cov_wrong.append(scored[0][0])
                conf[f"{ch}→{ranks[0]}"] += 1
            if ch in ranks:
                r5 += 1
        n = covered or 1
        fs = FontScore(
            edition=spec.edition_tag, n_queries=len(queries), covered=covered,
            recall1=r1 / n, recall5=r5 / n,
            cov_correct_p10=_pct(cov_ok, 10), cov_correct_med=_pct(cov_ok, 50),
            cov_wrong_med=_pct(cov_wrong, 50), cov_wrong_p90=_pct(cov_wrong, 90),
            margin=_pct(cov_ok, 10) - _pct(cov_wrong, 90) if cov_ok and cov_wrong else float("nan"),
            n_same=n_same,
            detail={"stroke_width": sw, "stroke_measured": meas, "book_stroke": book_w,
                    "norm_stroke": norm_stroke,
                    "top_confusions": sorted(conf.items(), key=lambda kv: -kv[1])[:15]})
        out.append(fs)
        log(f"  {spec.edition_tag:20s} 加粗 {sw}（笔宽 {meas:.2f}）覆盖 {covered}/{len(queries)} "
            f"recall@1 {fs.recall1:.3f} recall@5 {fs.recall5:.3f} cov正确 p10/中位 {fs.cov_correct_p10:.3f}/"
            f"{fs.cov_correct_med:.3f} cov错误 中位/p90 {fs.cov_wrong_med:.3f}/{fs.cov_wrong_p90:.3f} "
            f"margin {fs.margin:+.3f} same {n_same}")
    out.sort(key=lambda s: (-s.recall1, -s.margin))
    return out
