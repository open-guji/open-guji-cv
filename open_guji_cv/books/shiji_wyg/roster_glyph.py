"""职名页密排段的「字形库参与切分」（overview#450，S4 续）。

为什么要库
----------
vol01 p90 这类职名页，官衔字被刻工压扁到约 0.55 字宽高、上下字相压，整段一条墨带没有
白行。几何上分不清「两个压扁字」与「一个上下结构字」，投影自相关、等距网格、通用 OCR
都试过（cv `doc/pipeline_handbook.md` §13）：PP-OCR 会把「太子」高置信读成「李」。

本书字形库知道这本书的「太」「子」「李」各长什么样。把候选片段**裁到墨框后完全拉成方形**
（正好抵消压扁）再与全库刻例比相似度：真单字 0.71～0.87，两字合成一片 0.55～0.66，
半个字 ≈0.60——分得开。

为什么不用库里现成的 norm/HOG 特征
--------------------------------
`normalize_patch` 只允许 ±20% 的不等比拉伸，压扁到 0.55 的字被保留成扁的；实测用它 + HOG，
合字「太子→李」0.789 反而高于真单字 0.62～0.66。所以这里从刻例原图（`instances.patch_png`）
另算一份「全拉伸 32×32 模糊像素」向量，按库内容指纹缓存在进程里。

切法（`glyph_dp`）
-----------------
候选切点 = 投影局部极小 ∪ 每 6px 一点；片段高 ∈ [0.35, 1.35]×段宽；片分 = 库内最高相似度
− `TAU`，再减「片高偏离段内中位片高」的平方罚（两轮迭代估段字距）；DP 取总分最高的切法。

量（vol01 真原图，12 页 106 列目测小金标，2026-10-07）
-----------------------------------------------------
只精修「官衔区（全页『臣』行以上）里 ≥2.2em 的连续密排段、且该列无雙行」：
101/106 → 104/106；p90 第 3/4/8 列（27/21/20 字官衔）全对，其余 9 页零变化。
剩下 2 列是 p90 的雙行列，本模块不碰。
"""

from __future__ import annotations

import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

VEC_N = 32            # 向量边长
TAU = 0.62            # 片分门槛：真单字 ≥0.7、合字/半字 ≈0.55～0.66
PITCH_MU = 0.5        # 片高偏离段字距的平方罚权重
CAND_STEP = 6         # 候选切点：投影极小之外每这么多 px 补一个
RUN_MIN_EM = 2.2      # 只精修 ≥ 此 × em 的连续密排段
RUN_GAP_EM = 0.35     # 段内相邻墨带间隙上限（与 roster_segment.RUN_GAP 同口径）
MERGED_H = 1.05       # 几何切出的片高 > 此 × em 才算「疑似两字合一」
MERGED_MIN = 2        # 段内至少这么多个疑似合字片（或有 dense_guess）才交库重切
ACCEPT_GAIN = 0.045   # 库切法的片平均相似度至少比几何切法高这么多才采纳（vol01 实测：修对的段增益 0.050～0.17，劈错字的 ≤0.039）


def glyph_vec(ink: np.ndarray) -> np.ndarray | None:
    """二值 mask → 裁到墨框、**完全拉成方形**、轻模糊、去均值单位化的向量；墨太少返回 None。"""
    ys, xs = np.nonzero(ink)
    if len(ys) < 8:
        return None
    b = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    im = Image.fromarray(b).resize((VEC_N, VEC_N), Image.BILINEAR)
    v = ndi.gaussian_filter(np.asarray(im, np.float32) / 255.0, 0.8).ravel()
    v -= v.mean()
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


@dataclass
class GlyphScorer:
    X: np.ndarray           # [N, VEC_N²]，行已单位化
    chars: np.ndarray       # [N]

    def best(self, crops: list[np.ndarray]) -> list[tuple[float, str]]:
        """每个二值片段 → (库内最高相似度, 对应字)；墨太少的给 (-1, "")。"""
        vs, ok = [], []
        for c in crops:
            v = glyph_vec(c)
            ok.append(v is not None)
            vs.append(v if v is not None else np.zeros(self.X.shape[1], np.float32))
        if not vs:
            return []
        sims = np.stack(vs) @ self.X.T
        arg = sims.argmax(1)
        return [(float(sims[k, arg[k]]), str(self.chars[arg[k]])) if ok[k] else (-1.0, "")
                for k in range(len(vs))]

    @classmethod
    def from_rows(cls, rows: list[tuple[str, bytes]]) -> "GlyphScorer | None":
        X, Y = [], []
        for ch, png in rows:
            g = np.asarray(Image.open(io.BytesIO(png)).convert("L"))
            v = glyph_vec(g < 128)
            if v is not None:
                X.append(v)
                Y.append(ch)
        if not X:
            return None
        return cls(np.stack(X).astype(np.float32), np.array(Y))


_CACHE: dict[tuple, GlyphScorer | None] = {}


def load_scorer(db_path: str | Path, fingerprint: str, edition: str | None = None) -> GlyphScorer | None:
    """从 GlyphDB 读全部 exemplar 的刻例原图建打分器。按 (路径, 库指纹, edition) 缓存一份。"""
    key = (str(db_path), fingerprint, edition)
    if key in _CACHE:
        return _CACHE[key]
    p = Path(db_path)
    scorer = None
    if p.exists():
        sql = ("SELECT g.char, i.patch_png FROM exemplars e "
               "JOIN glyphs g ON g.glyph_id = e.glyph_id "
               "JOIN instances i ON i.instance_id = e.instance_id")
        args: tuple = ()
        if edition:
            sql += " WHERE g.edition_tag = ?"
            args = (edition,)
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as c:
            rows = c.execute(sql, args).fetchall()
        scorer = GlyphScorer.from_rows(rows)
    _CACHE.clear()                      # 只留一份：换库/换指纹就丢旧的
    _CACHE[key] = scorer
    return scorer


def glyph_dp(ink: np.ndarray, a: int, b: int, x0: int, x1: int,
             scorer: GlyphScorer) -> list[tuple[int, int, str, float]] | None:
    """把 [a,b) × [x0,x1) 这段密排墨按库打分切开。返回 [(y0, y1, 最像的字, 相似度)]；切不出返回 None。"""
    w, h = x1 - x0, b - a
    if w <= 0 or h <= 0:
        return None
    prof = ink[a:b, x0:x1].sum(1).astype(float)
    sm = np.convolve(prof, np.ones(5) / 5, mode="same")
    cand = {0, h} | {i for i in range(3, h - 3) if sm[i] <= sm[i - 3:i + 4].min() + 1e-9} \
        | set(range(0, h, CAND_STEP))
    cs = sorted(cand)
    pts = [cs[0]]
    for c in cs[1:]:
        if c - pts[-1] >= 4:
            pts.append(c)
    pts[-1] = h
    n = len(pts)
    pairs = [(i, j) for j in range(n) for i in range(j) if 0.35 * w <= pts[j] - pts[i] <= 1.35 * w]
    if not pairs:
        return None
    scored = scorer.best([ink[a + pts[i]:a + pts[j], x0:x1] for i, j in pairs])
    sc = dict(zip(pairs, scored))
    pitch = None
    segs: list[tuple[int, int]] = []
    for _ in range(2):                      # 第二轮用第一轮的中位片高当段字距
        best = [-1e18] * n
        back = [-1] * n
        best[0] = 0.0
        for j in range(1, n):
            for i in range(j):
                if (i, j) not in sc or best[i] < -1e17:
                    continue
                hh = pts[j] - pts[i]
                s = sc[(i, j)][0] - TAU - (PITCH_MU * ((hh - pitch) / pitch) ** 2 if pitch else 0.0)
                if best[i] + s > best[j]:
                    best[j], back[j] = best[i] + s, i
        if best[-1] < -1e17:
            return None
        segs = []
        j = n - 1
        while j > 0:
            segs.append((back[j], j))
            j = back[j]
        segs.reverse()
        pitch = float(np.median([pts[j] - pts[i] for i, j in segs]))
    return [(a + pts[i], a + pts[j], sc[(i, j)][1], sc[(i, j)][0]) for i, j in segs]
