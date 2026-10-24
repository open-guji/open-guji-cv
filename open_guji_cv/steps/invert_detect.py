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
  正文里的带上方总有字或框线，黑条上方 `CTX`（30–150 行）墨占比 < `MIN_BLANK_CTX` 就不报。
- **封面、书衣**（vol04 p2/129）：黑条在满是花纹的纸上。正文页上下文墨占比在 0.25 以内，
  上下任一侧 > `MAX_INK_CTX` 就不报。

十册重跑：已登记的 15 处全中，误报 13 页 → 2 页（vol06 p40、vol08 p67，都是抬头格下的粗横线，
和已登记的 vol02 p136 长相一样，几何上分不开，留给人审）。

## 1.2：上下边框都按位置排；建议修法照黑区实际形状圈（Sheldon 10-23 审 vol11–20 候选）

- **下边框**（vol16 p80/p104、vol20 p168）：1.1 只排了页顶外框。下框粗线一样「白缝接黑界行」，
  判法与上框对称——黑条下方 `CTX` 是空白地脚就不报。一句话：黑条在正文块最上沿或最下沿（外侧是
  空白天头、地脚）就是边框。
- **范围**：1.1 的建议修法是一段 `inverted_band`（逐列量上下沿再中值平滑），台阶形、一段高一段低、
  带只盖住半格的页范围都偏（vol11 p40 太大；vol13 p85/86、vol14 p87 略偏；vol17 p126 台阶被抹平）。
  1.2 改成 `inverted_poly`：按「窗里黑占多数」逐点圈出反色区（`band_region`），轮廓折成多边形，
  可以不是矩形、可以分成几块。

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
MIN_BLANK_CTX = 0.015  # 上（下）方比这还白 = 空白天头（地脚），黑条是上（下）边框
MAX_INK_CTX = 0.35     # 上下任一侧比这还黑 = 封面、书衣的花纹纸，不是正文页
REGION_BOX = (61, 15)  # 圈反色区：多数票窗（宽, 高）。高 15 行，薄带也圈得住
REGION_OPEN = (15, 41)  # 去横笔画（行）、去粘在带边的竖笔画与字块（像素宽）
REGION_CLOSE = 41      # 补带里的白字缺口
REGION_PAD = 150       # 往黑条上下各看多远（台阶带的高段可以超出黑条）


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


def band_region(gray: np.ndarray, box) -> np.ndarray:
    """黑条所在那块反色区的实际形状，布尔 mask（原图大小）。

    反色区就是「纸成了黑」的地方：在 `REGION_BOX` 那么大的窗里黑占多数（＝二值图上的横扁中值滤波，
    白字笔画占不到一半，正文区黑占不到一半）。窗竖向只有 15 行，所以薄带（vol12 p9 约 24 行）也圈得住；
    上下沿、左右端都是逐点量出来的，台阶、斜边、断开都照实跟着走。之后三步收拾：
    竖向开运算去掉横笔画（≤ `REGION_OPEN[0]` 行），横向开运算去掉粘在带边上的竖笔画、字块
    （≤ `REGION_OPEN[1]` 像素宽），闭运算＋填洞把带里的白字补实。每一步都只留碰到黑条外接框的块。
    """
    import cv2
    from scipy import ndimage as ndi

    x0, y0, x1, y1 = box
    ya, yb = max(0, y0 - REGION_PAD), min(gray.shape[0], y1 + REGION_PAD + 1)

    def touching(m):
        lab, _ = ndi.label(m)
        seed = lab[y0 - ya:y1 - ya + 1, x0:x1 + 1]
        return np.isin(lab, np.unique(seed[seed > 0]))

    m = cv2.blur((gray[ya:yb] < 128).astype(np.float32), REGION_BOX) > 0.5
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((REGION_OPEN[0], 1), np.uint8))
    m = touching(m)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, REGION_OPEN[1]), np.uint8))
    m = touching(m)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((REGION_CLOSE, REGION_CLOSE), np.uint8))
    m = ndi.binary_fill_holes(m)
    # 多数票窗在带的四角票不够，角上缺一块三角；同一行横向半窗内的黑补回来（只横向补，带上下沿外的笔画不沾）
    grow = cv2.dilate(m.astype(np.uint8), np.ones((1, REGION_BOX[0]), np.uint8)).astype(bool)
    out = np.zeros(gray.shape, bool)
    out[ya:yb] = m | (grow & (gray[ya:yb] < 128))
    return out


def region_polygons(mask: np.ndarray) -> list[list[list[int]]]:
    """mask 的外轮廓折成多边形（顶点 [x, y]），矮于 `MIN_H` 行的碎块不要。"""
    import cv2
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.approxPolyDP(c, 1.5, True)[:, 0].tolist() for c in cs if cv2.boundingRect(c)[3] >= MIN_H]


def suggest_rule(gray: np.ndarray, box, taken: np.ndarray | None = None) -> dict:
    """建议修法：一条 `inverted_poly`，多边形按黑区实际形状圈（`band_region`）。
    `taken` 是同页前面几条带已经圈走的区域，扣掉，免得同一块反两次又翻回去（vol15 p32 一页两条黑条连成一块）。
    圈不出来就退成黑条外接框的 `inverted_rect`。"""
    m = band_region(gray, box)
    if taken is not None:
        m &= ~taken
    polys = region_polygons(m)
    if not polys:
        x0, y0, x1, y1 = box
        return {"kind": "inverted_rect", "x0": x0, "x1": x1, "y0": y0, "y1": y1}
    return {"kind": "inverted_poly", "polygons": polys}


def in_body_text(ink: np.ndarray, box) -> bool:
    """黑条在正文里：上下都不是空白（天头、地脚——那是上下边框），上下都不是满纸花纹。"""
    x0, y0, x1, y1 = box
    near, far = CTX
    above = ink[max(0, y0 - far):max(0, y0 - near), x0:x1 + 1]
    below = ink[y1 + near:y1 + far, x0:x1 + 1]
    a = float(above.mean()) if above.size else 0.0
    b = float(below.mean()) if below.size else 0.0
    return min(a, b) >= MIN_BLANK_CTX and max(a, b) <= MAX_INK_CTX


def detect_inverted(gray: np.ndarray, *, min_flipped: int = MIN_FLIPPED) -> list[InvertedBand]:
    ink = gray < 128
    out = []
    taken = np.zeros(gray.shape, bool)
    for box in black_strips(ink):
        x0, y0, x1, y1 = box
        fill = float(ink[y0:y1 + 1, x0:x1 + 1].mean())
        if fill < MIN_INK or not in_body_text(ink, box):
            continue
        n = sum(is_flipped_rule(ink, box, s) for s in white_slits(ink, box))
        if n >= min_flipped:
            rule = suggest_rule(gray, box, taken)
            if rule["kind"] == "inverted_poly":
                from ..utils.preclean import poly_mask
                taken |= poly_mask(gray.shape, polygons=rule["polygons"])
            out.append(InvertedBand(bbox=box, flipped_rules=n, ink=round(fill, 3), rule=rule))
    return out


@register_step
class InvertDetectStep(Step):
    spec = StepSpec(
        id="invert_detect", title="Step0 反色带候选", version="1.2", unit="page",
        consumes=("raw_page",), produces=("inverted",), params=InvertDetectParams,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: InvertDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        return {"inverted": PageInverted(page=page, width=W, height=H,
                                         bands=detect_inverted(gray, min_flipped=p.min_flipped))}
