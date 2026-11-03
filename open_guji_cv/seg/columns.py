"""列宽均匀约束（2026-11-03 Sheldon 定：「列宽均匀是强约束，无论开始的算法还是后面的检查，都一定要把它好好检测出」）。

设计见 `doc/design/列宽均匀约束.md`。本模块只做几件看图、量数的事，不认识任何一套书：

- `ColumnSpec`：一套书的列宽约束（列数、内外列宽带、列距先验、strict/loose/off）。各书在 `book_defaults.yaml`
  的 `columns:` 里配，读进 `BookSpec.columns`。
- `check_columns`：列宽出带的列。Step1 产物 flag、交接闸、体检脚本同一口径。
- `ink_profile`／`rule_ridges`／`blank_mids`：整页沿界行斜率拉直后的墨投影、界行残段、字间空白中点（拟合的候选证据）。
- `fit_columns`：从带分的候选线里一次挑出 n+1 条、每列宽都在带里、总分最高（DP）。自由模式本来合格的页不用它。

坐标：一律是 Step1 的**规范空间**（右上原点，x 向左增大；原图 x = W−1−x），线的 x 取版框中高处。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import cv2
import numpy as np

#: 殿本 vol04–20 共 2,969 页正文实测（2026-10-23）：内列宽／页中位列宽 99.9% 在 0.907–1.088；
#: 首末列量到外框、偏宽，99.9% 在 0.84–1.26。缺省带取这组。
INNER_BAND = (0.9, 1.1)
#: Step1 产物里出带列的 flag 前缀（交接闸、体检、待审分类都认这个）
COL_WIDTH_FLAG = "col_width_out_of_band"
OUTER_BAND = (0.85, 1.3)


@dataclass(frozen=True)
class ColumnSpec:
    """一套书的列宽约束。`uniform`：strict＝出带就重拟合、拟合不出打 flag；loose＝只检查打 flag；off＝都不做。"""
    uniform: str = "strict"
    inner_band: tuple[float, float] = INNER_BAND
    outer_band: tuple[float, float] = OUTER_BAND
    pitch: float | None = None          # 列距先验（px，本册图源尺度）；None＝取本页列宽中位
    min_cols: int = 5                   # 正文列不到这么多（书名页、卷端大印页）不判

    @classmethod
    def from_dict(cls, d: dict | None) -> "ColumnSpec":
        d = dict(d or {})
        kw = {}
        if "uniform" in d:
            kw["uniform"] = str(d["uniform"])
            if kw["uniform"] not in ("strict", "loose", "off"):
                raise ValueError(f"columns.uniform 只能是 strict／loose／off，给的是 {kw['uniform']!r}")
        for k in ("inner_band", "outer_band"):
            if k in d:
                lo, hi = d[k]
                kw[k] = (float(lo), float(hi))
        if d.get("pitch") is not None:
            kw["pitch"] = float(d["pitch"])
        if "min_cols" in d:
            kw["min_cols"] = int(d["min_cols"])
        unknown = set(d) - {"uniform", "inner_band", "outer_band", "pitch", "min_cols"}
        if unknown:
            raise ValueError(f"columns 不认识的键：{sorted(unknown)}")
        return cls(**kw)

    def to_dict(self) -> dict:
        return {"uniform": self.uniform, "inner_band": list(self.inner_band),
                "outer_band": list(self.outer_band), "pitch": self.pitch, "min_cols": self.min_cols}


@dataclass
class ColumnCheck:
    pitch: float                                    # 量带用的列距
    ratios: list[float]                             # 每列宽／列距（列号 = 下标＋1）
    bad: list[int] = field(default_factory=list)    # 出带的列号（1 起）
    judged: bool = True                             # 正文列太少不判时 False

    @property
    def ok(self) -> bool:
        return not self.judged or not self.bad


def band_for(k: int, n: int, spec: ColumnSpec) -> tuple[float, float]:
    """第 k 列（0 起，共 n 列）的宽度带（× 列距）：首末列用外列带。"""
    return spec.outer_band if k in (0, n - 1) else spec.inner_band


def check_columns(xs: list[float], spec: ColumnSpec, *, skip: frozenset[int] | set[int] = frozenset()) -> ColumnCheck:
    """`xs`：N+1 条线（升序）。`skip`：不受带约束的列号（版心、贴页边的 edge 列）。
    列距取 `spec.pitch`，没有就取不跳过的列宽中位。"""
    n = len(xs) - 1
    widths = [xs[i + 1] - xs[i] for i in range(n)]
    body = [w for i, w in enumerate(widths) if i + 1 not in skip]
    if n < 1 or len(body) < spec.min_cols:
        return ColumnCheck(pitch=float(statistics.median(widths)) if widths else 0.0,
                           ratios=[], judged=False)
    pitch = spec.pitch or float(statistics.median(body))
    ratios = [w / pitch for w in widths]
    idx = [i for i in range(n) if i + 1 not in skip]
    bad = []
    for j, i in enumerate(idx):
        lo, hi = spec.outer_band if j in (0, len(idx) - 1) else spec.inner_band
        if not lo <= ratios[i] <= hi:
            bad.append(i + 1)
    return ColumnCheck(pitch=pitch, ratios=ratios, bad=bad)


# ── 证据 ─────────────────────────────────────────────────────────────

def _straight_px(W: int, xs: np.ndarray, ys: np.ndarray, slope: float, y_mid: float) -> np.ndarray:
    return np.rint(W - 1 - (xs[None, :] + slope * (ys[:, None] - y_mid))).astype(int)


def ink_profile(gray: np.ndarray, top: float, bot: float, slope: float, x0: float, x1: float,
                *, ink_threshold: int = 128, step: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """规范空间 [x0, x1) 逐 px 的墨占比：版框上下沿之间、按界行斜率 `slope` 拉直。返回 (xs, 占比)。出图的 px 算无墨。"""
    H, W = gray.shape[:2]
    top, bot = max(int(top), 0), min(int(bot), H - 1)
    xs = np.arange(int(np.ceil(x0)), int(x1))
    if bot - top < 10 or len(xs) == 0:
        return xs, np.zeros(len(xs))
    ys = np.arange(top, bot, step)
    px = _straight_px(W, xs, ys, slope, (top + bot) / 2.0)
    ok = (px >= 0) & (px < W)
    ink = np.where(ok, gray[ys[:, None], np.clip(px, 0, W - 1)] < ink_threshold, False)
    return xs, ink.mean(axis=0)


def rule_ridges(gray: np.ndarray, top: float, bot: float, slope: float, x0: float, x1: float,
                min_run: float, *, ink_threshold: int = 128, gap: int = 3, merge: int = 10) -> list[float]:
    """规范空间 (x0, x1) 里像界行的竖墨线：拉直后逐列量最长连续墨段（容 `gap` px 断口），≥ `min_run` 的列
    按 `merge` px 内取最长者归并。字的竖笔不过一格高，界行残段（哪怕只在天头一截）都比它长。"""
    H, W = gray.shape[:2]
    top, bot = max(int(top), 0), min(int(bot), H - 1)
    if bot - top < 10:
        return []
    ys = np.arange(top, bot)
    xs = np.arange(int(np.ceil(x0)), int(x1))
    if len(xs) == 0:
        return []
    px = _straight_px(W, xs, ys, slope, (top + bot) / 2.0)
    ok = (px >= 0) & (px < W)
    ink = np.where(ok, gray[ys[:, None], np.clip(px, 0, W - 1)] < ink_threshold, False).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((gap + 1, 1), np.uint8))
    run = np.zeros(len(xs), int)
    cur = np.zeros(len(xs), int)
    for row in ink:
        cur = (cur + 1) * row
        np.maximum(run, cur, out=run)
    out: list[tuple[int, int]] = []
    for i in np.flatnonzero(run >= min_run):
        if out and xs[i] - out[-1][0] <= merge:
            if run[i] > out[-1][1]:
                out[-1] = (int(xs[i]), int(run[i]))
        else:
            out.append((int(xs[i]), int(run[i])))
    return [float(x) for x, _ in out]


def blank_mids(xs: np.ndarray, prof: np.ndarray, *, blank: float = 0.01, min_w: int = 3) -> list[float]:
    """投影里墨占比 < `blank` 的连续段（宽 ≥ `min_w`）的中点。贴着窗口两头的段量不出中点，不算。"""
    out, start = [], None
    for i, v in enumerate(prof):
        if v < blank and start is None:
            start = i
        elif v >= blank and start is not None:
            if start > 0 and i - start >= min_w:
                out.append((float(xs[start]) + float(xs[i - 1])) / 2.0)
            start = None
    return out


def thin_peaks(xs: np.ndarray, prof: np.ndarray, *, min_peak: float = 0.02, half: int = 8) -> list[float]:
    """投影里的细峰（淡界行：断续印出、连不成残段）：峰值 ≥ `min_peak`、两侧 `half` px 外落到一半以下的局部极大。
    字的竖笔也会是细峰，调用方用 `flank_ink`（两侧墨）区分。"""
    out = []
    for i in range(half, len(prof) - half):
        v = prof[i]
        if (v >= min_peak and v >= prof[i - 1] and v > prof[i + 1]
                and prof[i - half] < v / 2 and prof[i + half] < v / 2):
            out.append(float(xs[i]))
    return out


def flank_ink(xs: np.ndarray, prof: np.ndarray, x: float, *, near: int = 6, far: int = 16,
              run: float = 0.6) -> float:
    """线 x 两侧 [near, far) px 的平均墨占比，取空的那一侧。字心里的假线两侧都是字（高）；界行至少一侧是字间空白
    （外框线外侧可能贴着版心条、邻页，内界行在密排页上可能一侧贴字）。
    x 落在一段墨占比 ≥ `run` 的实墨上（粗外框、笔画）时，从这段墨的两边起量，粗框自己的墨不算两侧墨。"""
    if len(xs) == 0:
        return 0.0
    base = int(xs[0])
    i = min(max(int(round(x)) - base, 0), len(prof) - 1)
    a = b = i
    if prof[i] >= run:
        while a > 0 and prof[a - 1] >= run:
            a -= 1
        while b < len(prof) - 1 and prof[b + 1] >= run:
            b += 1

    def side(i0, i1):
        i0, i1 = max(i0, 0), min(i1, len(prof))
        return float(prof[i0:i1].mean()) if i1 > i0 else 0.0
    return min(side(a - far, a - near), side(b + near + 1, b + far + 1))


def core_ink(xs: np.ndarray, prof: np.ndarray, x: float, *, half: int = 3) -> float:
    """线 x 本身 ±`half` px 的平均墨占比。真界行是墨（细峰），没印出的界行落在字缝里是空白；字心假线压在笔画上。"""
    if len(xs) == 0:
        return 0.0
    i = int(round(x)) - int(xs[0])
    i0, i1 = max(i - half, 0), min(i + half + 1, len(prof))
    return float(prof[i0:i1].mean()) if i1 > i0 else 0.0


# ── 拟合 ─────────────────────────────────────────────────────────────

@dataclass
class Cand:
    """一条候选线：规范空间 x、证据分（已扣墨）、调用方自带的负载（线形、是否插值等）。"""
    x: float
    score: float
    payload: object = None


def fit_columns(cands: list[Cand], n_lines: int, pitch: float, spec: ColumnSpec, *,
                first_max: float | None = None, last_min: float | None = None,
                even_w: float = 1.0) -> list[Cand] | None:
    """从候选里挑恰好 `n_lines` 条线（x 升序），相邻间距都在带里（首末列外列带、其余内列带，× `pitch`），
    目标＝证据分之和 − `even_w` × Σ|内列宽/列距 − 1|，取最大（首末列量到外框、本来偏宽，不计匀度）。`first_max`／`last_min`：第一条线不许大于、最后一条
    不许小于（调用方用来护住贴版框的外列，不许整网平移把它甩出去）。挑不出返回 None。"""
    pool = sorted(cands, key=lambda c: c.x)
    m, n = len(pool), n_lines
    if n < 2 or m < n:
        return None
    NEG = float("-inf")
    best = [[NEG] * n for _ in range(m)]
    prev: list[list[int | None]] = [[None] * n for _ in range(m)]
    for i, c in enumerate(pool):
        if first_max is None or c.x <= first_max:
            best[i][0] = c.score
    for k in range(1, n):
        lo, hi = band_for(k - 1, n - 1, spec)
        for i in range(m):
            xi = pool[i].x
            bi, bj = NEG, None
            for j in range(i):
                if best[j][k - 1] == NEG:
                    continue
                r = (xi - pool[j].x) / pitch
                if not lo <= r <= hi:
                    continue
                even = 0.0 if k - 1 in (0, n - 2) else even_w * abs(r - 1.0)
                v = best[j][k - 1] + pool[i].score - even
                if v > bi:
                    bi, bj = v, j
            best[i][k], prev[i][k] = bi, bj
    ends = [(best[i][n - 1], i) for i in range(m)
            if best[i][n - 1] != NEG and (last_min is None or pool[i].x >= last_min)]
    if not ends:
        return None
    i, k = max(ends)[1], n - 1
    chain = []
    while i is not None:
        chain.append(pool[i])
        i, k = prev[i][k], k - 1
    return chain[::-1]
