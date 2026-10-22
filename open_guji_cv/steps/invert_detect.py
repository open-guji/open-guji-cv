"""反色带候选：原图 → 本页疑似反色带（Step0，Step1 之前）。2026-10-22。

## 起因

扫描故障让一条横带黑白翻转：纸成黑、字和界行成白。vol07 p44 抬头框整格被翻，Step1 量不到第 7 列
抬头，「玉」整字丢出列图。此前反色带全靠人工登记（书 yaml `preclean:`，十册 15 处），辅助脚本
`scripts/scan_inverted_bands.py` 按行墨量找，误报几十页，贴版框的带还要另跑 `--edge`，没进管线。
Sheldon 10-22：应该放进自动跑；但外框粗线与窄反色带分不干净，定为**自动认＋送审，人点头才修**。

## 判据：界行的黑白翻了

反色带里，本该是黑细线的界行变成一道白缝，带外同一位置仍是黑界行。三步：

1. **长横黑条**：二值图横向先补 ≤ `GAP_FILL` 的白缝（翻白的界行、笔画），再只留 ≥ `MIN_RUN`
   像素长的黑段，竖向至少 `MIN_H` 行高、墨占比 ≥ `MIN_INK`。
2. **白缝**：黑条里 ≥ 70% 的行都是白的窄列（宽 2–14 像素）。
3. **翻白的界行**：白缝在 ≥ 60% 的行贯通，且黑条外（上或下 4–30 行）同一位置是一道细黑线
   （芯墨 ≥ 0.7，至少一侧白 ≤ 0.35）。≥ `MIN_FLIPPED` 道 → 候选。

## 1.1：先排掉三类不是正文里的带（Sheldon 10-22 嫌 1.0 误报多）

1.0 在殿本十册报的 13 页误报，按黑条在页上的处境分三类，各一条结构判据：

- **版框粗线**（vol02 p162、vol03 p48、vol08 p31）：上框线本身就是一道黑条，界行在它下面接着，
  一样「白缝接黑界行」。框线不过 11 行高；反色带至少翻掉半行字，`MIN_H` 由 10 升到 12。
- **页顶外框**（vol04 p72、vol05 p19/20、vol08 p59、vol09 p9/101）：黑条上方是空白天头。
  正文里的带上方总有字或框线，黑条上方 `CTX`（30–150 行）墨占比 < `MIN_INK_ABOVE` 就不报。
- **封面、书衣**（vol04 p2/129）：黑条在满是花纹的纸上。正文页上下文墨占比在 0.25 以内，
  上下任一侧 > `MAX_INK_CTX` 就不报。

十册重跑：已登记的 15 处全中，误报 13 页 → 2 页（vol06 p40、vol08 p67，都是抬头格下的粗横线，
和已登记的 vol02 p136 长相一样，几何上分不开，留给人审）。

殿本十册（1,707 页原图）：已登记的 15 处全中；另报 13 页，Sheldon 看过都是粗外框或封面（外框缺口
恰在界行处，一样「白缝接黑界行」）——所以只送审，不自动修。已在 `preclean:` 登记的页读的是修好的
图（`RunContext.raw_page`），带已经修掉，不会再报。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.inverted import InvertedBand, PageInverted

GAP_FILL = 15      # 横向补白缝（像素）
MIN_RUN = 150      # 长横黑条最短（像素，约 0.8 列宽）
MIN_H = 12         # 黑条最矮（行）；版框单线 5–9 行，上框粗线不过 11 行
MIN_INK = 0.55     # 黑条外接框墨占比下限
MIN_FLIPPED = 2    # 翻白界行最少几道
SLIT_W = (2, 14)   # 白缝宽（像素）
RULE_LOOK = (4, 30)  # 往黑条外看界行的行距
CTX = (30, 150)    # 量黑条上下文墨量的行距
MIN_INK_ABOVE = 0.015  # 上方比这还白 = 空白天头，黑条是页顶外框
MAX_INK_CTX = 0.35     # 上下任一侧比这还黑 = 封面、书衣的花纹纸，不是正文页


class InvertDetectParams(BaseModel):
    min_flipped: int = MIN_FLIPPED


def black_strips(ink: np.ndarray) -> list[tuple[int, int, int, int]]:
    """长横黑条的外接框 [(x0, y0, x1, y1)]，闭区间。"""
    import cv2
    m = ink.astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((1, GAP_FILL), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((1, MIN_RUN), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((4, 1), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 1), np.uint8))
    n, _lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    return [(int(x), int(y), int(x + w - 1), int(y + h - 1)) for x, y, w, h, _a in st[1:] if h >= MIN_H]


def white_slits(ink: np.ndarray, box) -> list[tuple[int, int]]:
    """黑条里 ≥ 70% 行是白的窄列段 [(a, c)]，闭区间，不含两端贴边的段。"""
    x0, y0, x1, y1 = box
    white = (~ink[y0:y1 + 1, x0:x1 + 1]).mean(0) >= 0.7
    idx = np.flatnonzero(np.diff(np.r_[0, white.astype(np.int8), 0]))
    out = []
    for s, e in zip(idx[::2], idx[1::2]):
        if s > 0 and e < white.size and SLIT_W[0] <= e - s <= SLIT_W[1]:
            out.append((x0 + int(s), x0 + int(e) - 1))
    return out


def is_flipped_rule(ink: np.ndarray, box, slit) -> bool:
    """白缝在黑条里贯通，黑条外同一位置是一道细黑线（界行）。"""
    _x0, y0, _x1, y1 = box
    a, c = slit
    H = ink.shape[0]
    if (~ink[y0:y1 + 1, a:c + 1]).all(1).mean() < 0.6:
        return False
    near, far = RULE_LOOK
    for ys, ye in ((max(0, y0 - far), y0 - near), (y1 + near + 1, min(H, y1 + far + 1))):
        if ye - ys < 5:
            continue
        core = ink[ys:ye, a:c + 1].mean()
        flank = min(ink[ys:ye, max(0, a - 10):max(0, a - 3)].mean() if a >= 4 else 1.0,
                    ink[ys:ye, c + 4:c + 11].mean() if c + 11 <= ink.shape[1] else 1.0)
        if core >= 0.7 and flank <= 0.35:
            return True
    return False


def suggest_rule(gray: np.ndarray, box) -> dict:
    """建议修法：一段 `inverted_band`（上下沿逐列量，搜索窗上下各放 20 行，探针取黑条中线）；
    量不到带（带上下没有列间纸列，如抬头框整格被翻）就退成黑条外接框的 `inverted_rect`。"""
    from ..utils.preclean import band_boundary
    x0, y0, x1, y1 = box
    band = {"kind": "inverted_band", "segments": [[x0, x1]], "y_lo": max(0, y0 - 20),
            "y_hi": y1 + 20, "y_probe": (y0 + y1) // 2}
    try:
        band_boundary(gray, y_lo=band["y_lo"], y_hi=band["y_hi"], y_probe=band["y_probe"])
    except ValueError:
        return {"kind": "inverted_rect", "x0": x0, "x1": x1, "y0": y0, "y1": y1}
    return band


def in_body_text(ink: np.ndarray, box) -> bool:
    """黑条在正文里：上方不是空白天头，上下都不是满纸花纹。"""
    x0, y0, x1, y1 = box
    near, far = CTX
    above = ink[max(0, y0 - far):max(0, y0 - near), x0:x1 + 1]
    below = ink[y1 + near:y1 + far, x0:x1 + 1]
    a = float(above.mean()) if above.size else 0.0
    b = float(below.mean()) if below.size else 0.0
    return a >= MIN_INK_ABOVE and max(a, b) <= MAX_INK_CTX


def detect_inverted(gray: np.ndarray, *, min_flipped: int = MIN_FLIPPED) -> list[InvertedBand]:
    ink = gray < 128
    out = []
    for box in black_strips(ink):
        x0, y0, x1, y1 = box
        fill = float(ink[y0:y1 + 1, x0:x1 + 1].mean())
        if fill < MIN_INK or not in_body_text(ink, box):
            continue
        n = sum(is_flipped_rule(ink, box, s) for s in white_slits(ink, box))
        if n >= min_flipped:
            out.append(InvertedBand(bbox=box, flipped_rules=n, ink=round(fill, 3), rule=suggest_rule(gray, box)))
    return out


@register_step
class InvertDetectStep(Step):
    spec = StepSpec(
        id="invert_detect", title="Step0 反色带候选", version="1.1", unit="page",
        consumes=("raw_page",), produces=("inverted",), params=InvertDetectParams,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: InvertDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        return {"inverted": PageInverted(page=page, width=W, height=H,
                                         bands=detect_inverted(gray, min_flipped=p.min_flipped))}
