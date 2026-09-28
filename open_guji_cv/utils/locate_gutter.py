# -*- coding: utf-8 -*-
"""`guji locate-gutter`：一张整叶（筒子页没剪开）扫描图里，版心在哪。给拆页用（#174）。

整理 Z18 拆 vol07 p128 / vol09 p258（一张图装四张半叶）时是手工找版心的，
两次都踩了同一个坑：**把普通界行当成版心边框**——版心宽（~210px）跟列距（~185px）
差不多，光看「两条竖线夹一条窄带」分不出来。

候选不新造：竖线全用 Step1 的 `peak_line_search.find_vertical_lines`（整页列投影 +
半高宽 + 位置角度联合精搜），版心就是它给出的某一对相邻线之间那条带。挑哪一对：

- **居中**（主判据）：版心在版面正中（左右半叶列数相同）。版面左右端见
  `_block_extent`（外框竖线，没有就取墨分位）；中心偏离版面中点 d，
  `exp(-½(d / (0.02·版面宽))²)`——版面 2300~3500px 时 σ≈47~70px，偏一列（120~185px）
  就只剩 ≲4%，隔壁那条界行天然被压下去；
- **空**（弱乘数）：版心里只有书名、卷次、鱼尾、叶码几处小字，量带内（两边各让 15% 宽）
  最长连续无墨行段占带高的比例。实测单用分不开（北行日錄正文短列、章末空列一样空，
  四庫版心 0.19 vs 正文 0.10），所以只乘一个 `(0.3+空)/1.3`，两对同样居中时才起作用。

置信度 = 1 − 次高分／最高分（0~1）：挑得干不干脆。两对差不多时就是拿不准，该去看图。

实测（2026-09-28，#174 评论有明细）：**57/58 块对**——
- 北行日錄筒子页 p3–56（54 页，版心 x≈1400）53 页对；错的 p39 是竖线池在版心里多出
  一条假线、把版心劈成两半，报的是左半（1332–1400），**置信度 0.03**；对的 57 块置信度
  5 分位 0.83、中位 0.95。所以 < 0.3 的一律人看；
- 四庫 vol09 p258 上下两块：1982–2169 / 1966–2152（人工 1968–2178 / 1960–2162）；
- 四庫 vol07 p128 上下两块：1967–2157 / 1957–2149。人工记的版心带牌记、宽 374px
  （1966–2340 / 1955–2332），工具只报到左边一段——**报的中线在版心里，宽度不可信**。
- 负结果：上一版拿竖线池两端、再一版拿上下横框两端当版面基准，北行日錄分别只对
  7/54、47/54（错的全挑成版心右邻那列——正是 Z18 踩的坑）。

只做定位，不裁图、不接管线。

坐标一律是**原图像素、左上原点、x 向右**（拆页脚本用的就是这个；不是 Step1 产物
那套右上原点）。线有倾角时报的是 `band` 中线高度处的 x。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .peak_line_search import find_vertical_lines

#: 居中项的宽度：版面宽的这个比例（σ）。
CENTER_SIGMA = 0.02
#: 「空」项的底：分数 = 居中 × (BLANK_FLOOR + 空) / (BLANK_FLOOR + 1)。
BLANK_FLOOR = 0.3
#: 量「空」时带的两侧各让出这么多宽度（版心边框线本身、线旁的残墨）。
SIDE_TRIM = 0.15
#: 一行算「有墨」：带宽内墨像素占比超过这个。
ROW_INK_MIN = 0.02
#: 一列算外框竖线：列墨占比超过这个（北行日錄外框 0.7~0.83，正文列 ≤0.3）。
RULE_COL_MIN = 0.5
#: 只在图宽这个比例范围里找版心（外框两侧不可能是版心）。
SEARCH = (0.25, 0.75)


@dataclass
class GutterPair:
    x_left: float          # 版心左边框线 x（原图坐标，左原点）
    x_right: float         # 版心右边框线 x
    center: float
    width: float
    central: float         # 居中项 0~1
    blank: float           # 空项 0~1（最长无墨行段 / 带高）
    score: float


@dataclass
class GutterResult:
    x: float | None                    # 版心中线 x；找不到为 None
    x_left: float | None
    x_right: float | None
    confidence: float                  # 0~1，最高分 − 次高分
    pitch: float | None                # 相邻竖线距的中位数（列距）
    n_lines: int
    width: int
    height: int
    band: tuple[int, int]
    extent: tuple[float, float] | None = None   # 版面左右端（居中的基准）
    extent_source: str = ""                     # 外框竖线 / 墨分位
    note: str = ""
    candidates: list[GutterPair] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["band"] = list(self.band)
        d["extent"] = None if self.extent is None else [round(v, 1) for v in self.extent]
        d["candidates"] = [{k: round(v, 3) for k, v in asdict(c).items()} for c in self.candidates]
        for k in ("x", "x_left", "x_right", "pitch"):
            if d[k] is not None:
                d[k] = round(d[k], 1)
        d["confidence"] = round(d["confidence"], 3)
        return d


def _longest_run(flags: np.ndarray) -> int:
    best = cur = 0
    for v in flags:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def _block_extent(binm: np.ndarray) -> tuple[float, float, str]:
    """版面（两个半叶合起来）的 x 范围，取中点当「居中」的基准。返回 (左, 右, 来源)。

    - 有贯穿全高的外框竖线（列墨占比 > `RULE_COL_MIN`、不贴图边、不是整片黑）→ 取最左／
      最右那条（北行日錄：外框列墨 0.7~0.83）；
    - 没有（四庫總目这批影印件根本没印版框界行）→ 取列墨质量的 0.5%／99.5% 分位。

    ⚠️ **别拿竖线池两端取中点**：池里常混进书边、扫描黑边上的假线，北行日錄 56 页里
    47 页因此整体偏一列、挑成版心右邻那列。也别拿上下横框的两端：两个半叶的框线高低
    差近 9px、又常断，量出来左右端能偏 60~200px（实测，负结果）。"""
    h, w = binm.shape
    cm = binm.mean(axis=0)
    edge = int(0.02 * w)
    rule = np.flatnonzero((cm > RULE_COL_MIN) & (cm < 0.95))
    rule = rule[(rule >= edge) & (rule < w - edge)]
    if len(rule) >= 2 and rule[-1] - rule[0] >= 0.5 * w:
        return float(rule[0]), float(rule[-1]), "外框竖线"
    cs = np.cumsum(cm)
    if cs[-1] <= 0:
        return 0.0, float(w), "整幅"
    cs = cs / cs[-1]
    return float(np.searchsorted(cs, 0.005)), float(np.searchsorted(cs, 0.995)), "墨分位"


def locate_gutter(gray: np.ndarray, *, band: tuple[int, int] | None = None,
                  ink_threshold: int = 128, top_k: int = 5) -> GutterResult:
    """找版心。`band=(y0, y1)`：只看这段高度（一张图上下装两叶时分开找，
    Z18 那两页上下块的版心就差了 8~16px）；不给就是整幅。"""
    h, w = gray.shape[:2]
    y0, y1 = band if band else (0, h)
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    sub = gray[y0:y1]
    mask = (sub < ink_threshold).astype(np.float64)
    hh = y1 - y0
    base = dict(width=w, height=h, band=(y0, y1))
    if mask.mean() < 1e-4:          # 白图：投影全零时 find_vertical_lines 会按 NMS 间距凑出一排假线
        return GutterResult(None, None, None, 0.0, None, 0, note="几乎没有墨", **base)
    lines = find_vertical_lines(mask)
    if len(lines) < 3:
        return GutterResult(None, None, None, 0.0, None, len(lines),
                            note=f"只找到 {len(lines)} 条竖线，不像整叶", **base)
    xs = np.array([m.position for m in lines], dtype=float)     # 带中线高度处的 x
    pitch = float(np.median(np.diff(xs)))
    binm = mask > 0
    lo, hi, src = _block_extent(binm)
    frame_mid = (lo + hi) / 2.0
    sigma = CENTER_SIGMA * (hi - lo)
    pairs: list[GutterPair] = []
    for a, b in zip(xs[:-1], xs[1:]):
        c = (a + b) / 2.0
        if not (SEARCH[0] * w <= c <= SEARCH[1] * w):
            continue
        trim = SIDE_TRIM * (b - a)
        xa, xb = int(round(a + trim)), int(round(b - trim))
        if xb - xa < 3:
            continue
        rows_ink = binm[:, xa:xb].mean(axis=1) > ROW_INK_MIN
        blank = _longest_run(~rows_ink) / max(hh, 1)
        central = float(np.exp(-0.5 * ((c - frame_mid) / sigma) ** 2))
        pairs.append(GutterPair(float(a), float(b), float(c), float(b - a),
                                central, float(blank), central * (BLANK_FLOOR + blank) / (BLANK_FLOOR + 1)))
    if not pairs:
        return GutterResult(None, None, None, 0.0, pitch, len(lines),
                            note="中间一带没有竖线对", **base)
    pairs.sort(key=lambda p: -p.score)
    best = pairs[0]
    second = pairs[1].score if len(pairs) > 1 else 0.0
    conf = 0.0 if best.score <= 0 else max(0.0, min(1.0, 1.0 - second / best.score))
    note = ""
    if best.central < 0.5:
        note = "离版面中点最近的一对也偏了 1.2σ 以上：可能不是整叶（已剪开的半叶），或竖线没找全"
    return GutterResult(best.center, best.x_left, best.x_right, conf, pitch, len(lines),
                        extent=(lo, hi), extent_source=src,
                        note=note, candidates=pairs[:top_k], **base)
