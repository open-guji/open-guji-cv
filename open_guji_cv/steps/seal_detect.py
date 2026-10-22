"""印章定位：原图＋版框 → 本页每方印的类别与外框。印章系统化第 1 期（2026-10-22）。

## 起因

用户 10-22：「在整个页面一开始、整个识别开始的时候就确定出来印章在什么位置，后边就不用再识别了。」
此前印章由四段代码各认一遍（`occlusion.page_occluded` 的格级密度、`occlusion.find_seal_box` 的
窗口模板、`row_segment._empty_zone_seal` 的表空段墨团、碎墨判空），都在切完格之后，判得也不一致。
这一步紧跟 Step1 版框（只用版框定大印的位置，Step1 本身不识别字），在切分、识别之前；
产物 `seals` 是后面各步认印的唯一来源（第 2 期起改各步去读它）。

## 两类印、两条判据（殿本四库总目十册 1,707 页普查）

1. **大印 `stain`**（卷首叶 p2/p3、卷端页的藏书印）：印泥斑驳，页面上是成片的「中等墨点」
   （面积 `DOT_AREA` 内的连通块，太小是噪声、太大是字的笔画）。按 `GRID` 像素网格数墨点、
   3×3 平滑，≥ `HOT` 的格连成区，区内峰值 ≥ `min_peak` 才算印。印近于方形，区的宽高比
   不在 `ASPECT` 内的不算——各册 p2 的书签条（细长，满是碎墨）就是这样排掉的。
   十册：印页峰值 23.9–42.4，无印页 ≤ 19。密度只用来判**有没有**大印；位置有更强的规律
   （Sheldon 10-22）：印紧贴版框上边与右边，宽正好是整个版框（九列），高与宽相等。所以外框
   取版框右上角起、边长＝版框宽的正方形（`stain_square`，`source="frame"`）；页面弯曲带来的
   几十像素误差不管。读不到版框才退回密度区的外接框（`source="density"`）。
2. **小印 `crisp`**（卷末「乾隆御覽之寶」）：模板（`config/seal_templates/`）在 1/4 降采样图上
   整页搜。分数不用 NCC——印压在正文上时印里有字，NCC 掉到 0.3（vol09 p265 原来认不出）——
   而用「模板笔画处有墨的比例 − 模板空白处有墨的比例」：印下压字只会抬高第二项一点，
   第一项仍接近 1。笔画覆盖 ≥ `min_cover` 且分数 ≥ `min_score` 才算印。十册：印页覆盖
   0.68–0.87、分数 0.29–0.80；无印页覆盖 ≤ 0.56、分数 ≤ 0.19。

## 人核覆盖

书级 `params.seal_detect.overrides`：`{页号: [{kind, bbox}, …]}`，写了的页整页以它为准
（空表＝本页无印），`source="manual"`。bbox 是规范空间（右上原点）。算法认不准的个别页用它补，
不往判据里堆特例。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from ..core.anchor import bbox_tl_to_tr
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.seals import PageSeals, Seal

SEAL_TPL_DIR = Path(__file__).resolve().parents[2] / "config" / "seal_templates"

DOT_AREA = (3, 150)    # 中等墨点的面积（像素），同 occlusion.OCC_AREA_MIN/MAX
GRID = 150             # 墨点计数网格（像素）
HOT = 12               # 平滑后 ≥ 这个数的格连成区
ASPECT = (0.5, 2.0)    # 大印区宽高比
SCALE = 0.25           # 小印模板搜索的降采样比
STROKE_DILATE = 9      # 模板笔画膨胀（原分辨率像素），容纳印的错位与晕染


class SealDetectParams(BaseModel):
    min_peak: float = 20.0
    min_cover: float = 0.6
    min_score: float = 0.25
    overrides: dict[int, list[dict]] = Field(default_factory=dict)
    """页号 → 人核的印列表 `[{"kind": "stain"|"crisp", "bbox": [x0, y0, x1, y1]}]`（规范空间）；空表＝无印。"""


def stain_seals(gray: np.ndarray, *, min_peak: float) -> list[tuple[tuple[int, int, int, int], float]]:
    """大印：[(左上原点 bbox [x0, y0, x1, y1], 峰值密度)]。"""
    import cv2
    ink = (gray < 128).astype(np.uint8)
    _n, _lab, st, cen = cv2.connectedComponentsWithStats(ink, connectivity=8)
    area = st[:, 4]
    dot = (area >= DOT_AREA[0]) & (area <= DOT_AREA[1])
    dot[0] = False
    H, W = gray.shape[:2]
    grid = np.zeros((H // GRID + 1, W // GRID + 1), np.float32)
    for x, y in cen[dot]:
        grid[int(y) // GRID, int(x) // GRID] += 1
    dens = cv2.blur(grid, (3, 3), borderType=cv2.BORDER_CONSTANT)
    hot = (dens >= HOT).astype(np.uint8)
    n, lab, rs, _ = cv2.connectedComponentsWithStats(hot, connectivity=4)
    out = []
    for i in range(1, n):
        peak = float(dens[lab == i].max())
        gx, gy, gw, gh = rs[i, :4]
        if peak < min_peak or not ASPECT[0] <= gw / gh <= ASPECT[1]:
            continue
        out.append(((int(gx * GRID), int(gy * GRID), int(min(W, (gx + gw) * GRID)), int(min(H, (gy + gh) * GRID))),
                    round(peak, 2)))
    return out


@lru_cache(maxsize=1)
def _templates() -> tuple[tuple[str, np.ndarray], ...]:
    """[(文件名, 降采样后的笔画掩码 float32)]；目录缺失就是空元组（认不出小印）。"""
    import cv2

    from ..utils.image_io import imread
    out = []
    if SEAL_TPL_DIR.is_dir():
        for f in sorted(SEAL_TPL_DIR.glob("*.png")):
            im = imread(str(f), cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            k = np.ones((STROKE_DILATE, STROKE_DILATE), np.uint8)
            stroke = cv2.dilate((im < 128).astype(np.uint8), k).astype(np.float32)
            small = cv2.resize(stroke, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
            out.append((f.name, (small > 0.5).astype(np.float32)))
    return tuple(out)


def crisp_seals(gray: np.ndarray, *, min_cover: float, min_score: float, templates=None
                ) -> list[tuple[tuple[int, int, int, int], float, str]]:
    """小印：各模板整页最好的一处里、过了门槛的最高分那个 [(左上原点 bbox, 分数, 模板名)]；都不过就是空表。"""
    import cv2
    templates = _templates() if templates is None else templates
    ink = cv2.resize((gray < 128).astype(np.float32), None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    ink = (cv2.dilate(ink, np.ones((2, 2), np.uint8)) > 0.2).astype(np.float32)   # 降采样后补一像素，笔画细处不断
    best = None
    for name, stroke in templates:
        h, w = stroke.shape
        if ink.shape[0] < h or ink.shape[1] < w:
            continue
        blank = 1.0 - stroke
        cover = cv2.filter2D(ink, -1, stroke / stroke.sum(), anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        noise = cv2.filter2D(ink, -1, blank / blank.sum(), anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        cover, noise = cover[:ink.shape[0] - h + 1, :ink.shape[1] - w + 1], noise[:ink.shape[0] - h + 1, :ink.shape[1] - w + 1]
        score = cover - noise
        _mn, mx, _ml, (px, py) = cv2.minMaxLoc(score)
        if cover[py, px] >= min_cover and mx >= min_score and (best is None or mx > best[0]):
            best = (float(mx), px, py, w, h, name)
    if best is None:
        return []
    score, px, py, w, h, name = best
    x0, y0 = int(round(px / SCALE)), int(round(py / SCALE))
    return [((x0, y0, x0 + int(round(w / SCALE)), y0 + int(round(h / SCALE))), round(score, 4), name)]


def stain_square(borders) -> tuple[float, float, float, float] | None:
    """大印外框（右上原点）：版框右上角起、边长＝版框宽的正方形。量在上框处；读不到上框或竖线返回 None。"""
    if borders is None or borders.top is None or len(borders.verticals) < 2:
        return None
    ty = float(borders.top.y_at_right)
    xs = [float(v.x_at_top) + float(v.slope) * ty for v in borders.verticals]
    xr, xl = min(xs), max(xs)
    return (xr, ty, xl, ty + (xl - xr))


def detect_seals(gray: np.ndarray, p: SealDetectParams, borders=None) -> list[Seal]:
    W = gray.shape[1]
    stains = stain_seals(gray, min_peak=p.min_peak)
    square = stain_square(borders) if stains else None
    if square is not None:          # 一页只有一方大印，位置按版框定
        out = [Seal(kind="stain", bbox=square, score=max(s for _b, s in stains), source="frame")]
    else:
        out = [Seal(kind="stain", bbox=bbox_tl_to_tr(b, W), score=s, source="density") for b, s in stains]
    out += [Seal(kind="crisp", bbox=bbox_tl_to_tr(b, W), score=s, source="template", template=t)
            for b, s, t in crisp_seals(gray, min_cover=p.min_cover, min_score=p.min_score)]
    return out


@register_step
class SealDetectStep(Step):
    spec = StepSpec(
        id="seal_detect", title="印章定位", version="1.1", unit="page",   # 1.1：大印外框按版框定（正方形）
        consumes=("raw_page", "borders"), produces=("seals",), params=SealDetectParams,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: SealDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        if page in p.overrides:
            seals = [Seal(kind=s["kind"], bbox=tuple(s["bbox"]), score=1.0, source="manual")
                     for s in p.overrides[page]]
        else:
            seals = detect_seals(gray, p, ctx.product("borders", page))
        return {"seals": PageSeals(page=page, width=W, height=H, seals=seals)}
