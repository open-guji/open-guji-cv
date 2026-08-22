"""版面几何：页面形变的标定与评测（错切 / 射影 / 列距 / 列相位）。

为什么要单独拆成一步
--------------------
「界行竖线混进图块」这个下游缺陷，追到底是**页面几何**的问题：deskew 把
横线摆平了，竖线仍可能斜着走，甚至左右两侧收敛（射影）。这些量原先埋在
`segment` 里，只能靠下游 flag 率**间接**衡量——每改一次判据就得重跑
segment → chars 全链，几百个图块内容一变，实例级人工标注全部失效
（实测两轮：第一轮 15 个失效、第二轮 59 个）。

金标为什么不会过期
------------------
本数据集的金标是**界行竖线在图像里的位置**——它是图像自身的性质，不是
算法输出的性质。算法怎么改，界行还在原地。这和 `char-segmentation/instances`
形成对照：那里的 `page:col:idx` 一重跑就漂，只能反复重标。

金标记什么
----------
每条界行记它在**三个高度**（上/中/下）的 x。一条线三个点，同时钉住三件事：

- 它在哪（列边界的直接证据）；
- 它斜不斜（三点不齐 = 有错切/旋转残余）；
- 全页的线是平行还是收敛（各线斜率一致 = 错切；随 x 系统变化 = **射影**）。

只记中点的话，后两件事就没法判——而它们正是「该做错切校正还是该做射影
矫正」的判据。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1

# 三个采样高度占页高的比例（避开上下版框横线所在的极边）
BAND_FRACS = (0.16, 0.50, 0.84)


@dataclass
class RuleLine:
    """一条界行/版框竖线在三个高度上的 x。"""
    x_top: float
    x_mid: float
    x_bot: float
    kind: str = "rule"          # rule（界行）| frame（版框竖线）

    @property
    def slope(self) -> float:
        """dx/dy，用上下两点算（y 间距由 PageGeometry.band_ys 给出）。"""
        return self.x_bot - self.x_top      # 未归一化；除以 dy 由外部做

    def x_at(self, which: str) -> float:
        return {"top": self.x_top, "mid": self.x_mid, "bot": self.x_bot}[which]

    @property
    def xs(self) -> tuple[float, float, float]:
        return (self.x_top, self.x_mid, self.x_bot)


@dataclass
class PageGeometry:
    """一页的版面几何金标。"""
    book: str
    page: str
    image_size: dict                     # {"width": int, "height": int}
    band_ys: list[float]                 # 三个采样高度的 y
    rules: list[RuleLine] = field(default_factory=list)
    n_cols: int | None = None
    page_class: str | None = None
    label_origin: str = "human"          # 候选自动生成，逐页人工目视确认
    schema_version: int = SCHEMA_VERSION

    # ── 派生量：形变性质的判据 ──────────────────────────

    def slopes(self) -> list[float]:
        """逐条界行的 dx/dy。"""
        dy = self.band_ys[2] - self.band_ys[0]
        if dy <= 0:
            return []
        return [(r.x_bot - r.x_top) / dy for r in self.rules]

    def shear(self) -> float:
        """全页共同的错切量：逐条斜率的中位数。"""
        s = self.slopes()
        return float(np.median(s)) if s else 0.0

    def projective_span(self) -> float:
        """斜率随 x 的**系统**变化量（跨整页）。

        错切下所有界行平行，此量为 0；射影下线收敛于灭点，斜率随 x 线性
        变化，此量即两端斜率之差。它和「斜率的随机散布」分得开——后者是
        测量噪声与刻版不齐，不随 x 走。
        """
        s = self.slopes()
        if len(s) < 4:
            return 0.0
        x = np.array([r.x_mid for r in self.rules], float)
        k = float(np.polyfit(x, np.array(s), 1)[0])
        return k * float(x.max() - x.min())

    def slope_scatter(self) -> float:
        """斜率的随机散布（去掉随 x 的系统分量之后）。"""
        s = self.slopes()
        if len(s) < 4:
            return 0.0
        x = np.array([r.x_mid for r in self.rules], float)
        fit = np.polyval(np.polyfit(x, np.array(s), 1), x)
        return float(np.std(np.array(s) - fit))

    def spacings(self, which: str = "mid") -> list[float]:
        xs = sorted(r.x_at(which) for r in self.rules)
        return [b - a for a, b in zip(xs, xs[1:])]

    def period(self) -> float:
        """列距：相邻界行间距的中位数（对缺条界行免疫）。"""
        d = [g for g in self.spacings("mid") if g > 0]
        return float(np.median(d)) if d else 0.0

    def foreshortening(self) -> float:
        """列距沿 x 的系统变化占列距的比例——射影的另一个独立证据。"""
        xs = sorted(r.x_mid for r in self.rules)
        gaps = [(a + b) / 2 for a, b in zip(xs, xs[1:])], \
               [b - a for a, b in zip(xs, xs[1:])]
        p = self.period()
        if len(gaps[1]) < 4 or p <= 0:
            return 0.0
        m = [i for i, g in enumerate(gaps[1]) if 0.6 * p < g < 1.6 * p]
        if len(m) < 4:
            return 0.0
        cx = np.array([gaps[0][i] for i in m], float)
        cg = np.array([gaps[1][i] for i in m], float)
        k = float(np.polyfit(cx, cg, 1)[0])
        return k * float(cx.max() - cx.min()) / p

    # ── 序列化 ────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PageGeometry":
        d = dict(d)
        d.pop("schema_version", None)
        rules = [RuleLine(**r) for r in d.pop("rules", [])]
        return cls(rules=rules, **d)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
            encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "PageGeometry":
        return cls.from_dict(json.loads(
            Path(path).read_text(encoding="utf-8")))
