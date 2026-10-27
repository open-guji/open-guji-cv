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
   只有宽 ≥ `BIG_FRAC`×版框宽的密度区才按大印套正方形（1.2，殿本 vol21–50 首跑）：卷末小印印得淡时
   碎墨也成一块密度区，但只有 600–900px 宽，原来也套了整页正方形，把大半页正文判成遮挡（vol35 p173 42 格）。
   窄区（≤ `SMALL_FRAC`）落在版框里、页上又没认出小印时，在这块里找模板最像的位置，分数 ≥ `SMALL_SCORE`
   就按小印记，否则不算印。
2. **小印 `crisp`**（卷末「乾隆御覽之寶」）：模板（`config/seal_templates/`）在 1/4 降采样图上
   整页搜。分数不用 NCC——印压在正文上时印里有字，NCC 掉到 0.3（vol09 p265 原来认不出）——
   而用「模板笔画处有墨的比例 − 模板空白处有墨的比例」：印下压字只会抬高第二项一点，
   第一项仍接近 1。笔画覆盖 ≥ `min_cover` 且分数 ≥ `min_score` 才算印。十册：印页覆盖
   0.68–0.87、分数 0.29–0.80；无印页覆盖 ≤ 0.56、分数 ≤ 0.19。vol21–50 卷末印更淡（覆盖 0.50–0.58），
   门槛 1.2 起由 0.6 降到 0.5，分数门槛不变。

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
#: 密度区宽 ≥ 这个比例 × 版框宽才是大印（按版框定正方形外框）。殿本 vol21–50 普查：大印区 1500–1950px（版框约 1650），
#: 卷末小印（乾隆御覽之寶）印得淡、模板没过门槛时，它的碎墨也会成一块密度区，只有 600–900px 宽
BIG_FRAC = 0.75
#: 密度区宽 ≤ 这个比例 × 版框宽、一半以上落在版框里：按小印算，外框取模板在这块里最像的位置
SMALL_FRAC = 0.55
#: 按小印算时模板分数的下限：卷末淡印 0.23–0.43；页底、页角的碎墨块（vol47 p7/p63/p87、vol46 p95）≤ 0.16
SMALL_SCORE = 0.2
#: 小印模板量在的页面尺度：殿本原扫描的版框宽（px）。版框宽与它差出 SCALE_TOL 以上的页，搜小印时按比例降采样，
#: 让模板和页上的印一样大（1.3，换图源 siku-qiefen-v2 缩到 0.66–0.79 倍，模板不缩就认不出卷末小印：vol15 新 p151、
#: vol28 新 p192、vol40 新 p173）。大印的墨点密度不跟着缩放：试过整页缩放回原尺度，卷端大印（vol28 新 p103）反而测不出
FRAME_W_REF = 1650.0
SCALE_TOL = 0.15


class SealDetectParams(BaseModel):
    min_peak: float = 20.0
    min_cover: float = 0.5
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


def crisp_seals(gray: np.ndarray, *, min_cover: float, min_score: float, templates=None, k: float = 1.0
                ) -> list[tuple[tuple[int, int, int, int], float, str]]:
    """小印：各模板整页最好的一处里、过了门槛的最高分那个 [(左上原点 bbox, 分数, 模板名)]；都不过就是空表。
    `k`：页图相对原扫描的放大倍数（`frame_scale`）；页图按 SCALE×k 降采样，印和模板一样大。"""
    import cv2
    templates = _templates() if templates is None else templates
    f = SCALE * k
    ink = cv2.resize((gray < 128).astype(np.float32), None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
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
    x0, y0 = int(round(px / f)), int(round(py / f))
    return [((x0, y0, x0 + int(round(w / f)), y0 + int(round(h / f))), round(score, 4), name)]


def frame_scale(square) -> float:
    """页图相对殿本原扫描的放大倍数（原尺度版框宽 `FRAME_W_REF` ÷ 本页版框宽）；读不到版框或差不到 `SCALE_TOL` 为 1。"""
    if square is None or square[2] <= square[0]:
        return 1.0
    k = FRAME_W_REF / (square[2] - square[0])
    return k if abs(k - 1) > SCALE_TOL else 1.0


def stain_square(borders) -> tuple[float, float, float, float] | None:
    """大印外框（右上原点）：版框右上角起、边长＝版框宽的正方形。量在上框处；读不到上框或竖线返回 None。"""
    if borders is None or borders.top is None or len(borders.verticals) < 2:
        return None
    ty = float(borders.top.y_at_right)
    xs = [float(v.x_at_top) + float(v.slope) * ty for v in borders.verticals]
    xr, xl = min(xs), max(xs)
    return (xr, ty, xl, ty + (xl - xr))


@lru_cache(maxsize=8)
def _template_stroke(name: str):
    """模板 `name` 原分辨率的笔画掩码（膨胀 `STROKE_DILATE`，uint8 0/1）；读不到为 None。"""
    import cv2

    from ..utils.image_io import imread
    try:
        im = imread(str(SEAL_TPL_DIR / name), cv2.IMREAD_GRAYSCALE)
    except OSError:
        im = None
    if im is None:
        return None
    return cv2.dilate((im < 128).astype(np.uint8), np.ones((STROKE_DILATE, STROKE_DILATE), np.uint8))


def stroke_mask(seal: Seal, height: int, width: int) -> np.ndarray | None:
    """小印笔画在整页上的覆盖区（左上原点、页图大小的 0/1 掩码）：命中模板的笔画放到外框处。大印或读不到模板为 None。"""
    if seal.kind != "crisp" or not seal.template:
        return None
    st = _template_stroke(seal.template)
    if st is None:
        return None
    x0, y0, x1, y1 = (int(round(v)) for v in bbox_tl_to_tr(seal.bbox, width))
    out = np.zeros((height, width), np.uint8)
    if x1 > x0 and y1 > y0 and abs((x1 - x0) / st.shape[1] - 1) > SCALE_TOL:
        import cv2                  # 缩小了的页图（`frame_scale`）：模板笔画按印框大小缩放
        st = cv2.resize(st, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    h, w = st.shape
    a, b = max(0, y0), min(height, y0 + h)
    c, d = max(0, x0), min(width, x0 + w)
    if a < b and c < d:
        out[a:b, c:d] = st[a - y0:b - y0, c - x0:d - x0]
    return out


def _in_frame(b, frame, W) -> float:
    """左上原点的框 `b` 落在版框（右上原点 (x0, y0, x1, y1)）里的面积比例。"""
    x0, y0, x1, y1 = bbox_tl_to_tr(b, W)
    fx0, fy0, fx1, fy1 = frame
    ov = max(0.0, min(x1, fx1) - max(x0, fx0)) * max(0.0, min(y1, fy1) - max(y0, fy0))
    return ov / max((x1 - x0) * (y1 - y0), 1.0)


def _crisp_in(gray: np.ndarray, b, k: float = 1.0) -> tuple[tuple[int, int, int, int], float, str] | None:
    """在密度区 `b`（左上原点）外扩一格的范围里找模板最像的位置（不设门槛）；区太小放不下模板就返回 None。"""
    H, W = gray.shape[:2]
    x0, y0 = max(0, b[0] - GRID), max(0, b[1] - GRID)
    x1, y1 = min(W, b[2] + GRID), min(H, b[3] + GRID)
    hits = crisp_seals(gray[y0:y1, x0:x1], min_cover=0.0, min_score=-1.0, k=k)
    if not hits:
        return None
    (a, c, d, e), score, name = hits[0]
    return (a + x0, c + y0, d + x0, e + y0), score, name


def detect_seals(gray: np.ndarray, p: SealDetectParams, borders=None) -> list[Seal]:
    W = gray.shape[1]
    stains = stain_seals(gray, min_peak=p.min_peak)
    full = stain_square(borders)
    k = frame_scale(full)
    crisp = crisp_seals(gray, min_cover=p.min_cover, min_score=p.min_score, k=k)
    square = full if stains else None
    out = []
    if square is None:
        out += [Seal(kind="stain", bbox=bbox_tl_to_tr(b, W), score=s, source="density") for b, s in stains]
    else:
        fw = square[2] - square[0]
        big = [s for b, s in stains if b[2] - b[0] >= BIG_FRAC * fw]
        if big:                     # 一页只有一方大印，位置按版框定
            out.append(Seal(kind="stain", bbox=square, score=max(big), source="frame"))
        bottom = getattr(getattr(borders, "bottom", None), "y_at_right", None)
        frame = (square[0], square[1], square[2], float(bottom) if bottom is not None else float(gray.shape[0]))
        if not crisp:
            # 卷末小印印得淡、模板没过门槛（vol35 p173、vol46 p225），碎墨成了一小块密度区：按小印记，
            # 不再按大印套整个版框宽的正方形（那会把大半页正文判成遮挡）
            for b, _s in stains:
                if b[2] - b[0] <= SMALL_FRAC * fw and _in_frame(b, frame, W) >= 0.5:
                    hit = _crisp_in(gray, b, k)
                    if hit is not None and hit[1] >= SMALL_SCORE:
                        crisp = [hit]
                        break
    out += [Seal(kind="crisp", bbox=bbox_tl_to_tr(b, W), score=s, source="template", template=t)
            for b, s, t in crisp]
    return out


@register_step
class SealDetectStep(Step):
    spec = StepSpec(
        id="seal_detect", title="印章定位", version="1.3", unit="page",   # 1.3：版框宽偏离原扫描尺度 15% 以上的页（换图源 siku-qiefen-v2），小印模板按比例匹配、笔画覆盖区按印框大小缩放；1.2：只有够宽的密度区才按大印套版框正方形，窄的按小印取模板位置；小印覆盖门槛 0.6→0.5（vol21–50 卷末印淡）；1.1：大印外框按版框定（正方形）
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
