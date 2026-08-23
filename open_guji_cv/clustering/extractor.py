"""M1 字符提取：Phase 3 字符网格 → 单字图块数据集（phase4_chars/）。

本模块之后，下游不再需要读取整页图像与版面 JSON。

输出：
  phase4_chars/
    index.jsonl                     每行一个 CharInstance
    patches/{page}/{col}_{idx}.png  灰度图块（bbox 外扩 padding）
    meta.json                       参数快照 + 统计
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread, imwrite
from .ids import make_id
from .normalize import NORM_SIZE, normalize_patch

BINARY_THRESHOLD_PATCH = 128
PADDING_RATIO = 0.08
MIN_INK_RATIO = 0.01
BOUNDARY_BAND = 0.10       # 图块上下各此比例的高度算「边缘带」
BOUNDARY_INK_T = 0.025     # 边缘带墨量占全图块墨量超此 → 标 boundary_ink

# ── 缺陷自检：确定层阈值（实测 0 误报，可直接自动处理）────────────
DEFECT_BAND = 0.18         # 判「整体落在上/下边缘带内」用的带宽
RULE_BAR_H = 0.90          # 竖线连通体的最小高度占比
RULE_BAR_W = 0.10          # 竖线连通体的最大宽度占比
RULE_BAR_INK = 0.02        # 竖线墨量占全图块墨量的下限
EDGE_BLOB_INK = 0.03
EDGE_BLOB_GAP = 0.10       # 带内连通体离本字主体的纵向间隙超此（× 图块高）
                           # 才算邻字残余。残余隔着整条字间空白（实测 87:1:18
                           # 的真残余 +0.206），本字自己的分离部件贴着主体
                           # （「冬」的下两点 +0.015、其余 clean 全为负值=重叠）。
                           # 没有这一条，格线吸附收紧图块后「冬」的两点整体
                           # 落进底部带，被误判成残余——确定层零误报因此失守       # 边缘带整体连通体的墨量下限
FRAME_BAR_W = 0.85         # 横条连通体的最小宽度占比
FRAME_BAR_H = 0.30         # 横条连通体的最大高度占比
FRAME_BAR_N = 2            # 满宽横条达此条数 → 版框而非「一」
# ── 缺陷自检：疑似层阈值（有误报，进人工审查队列）──────────────
WIDE_GAP_T = 0.12          # 主体之间最大水平空隙占图块宽度超此 → 疑似跨列
MIN_SPAN_INK = 0.02        # 参与空隙计算的连通体墨量下限
# ── 贴边界行残条清除 ─────────────────────────────────────
# 磨损界行断成的短残段够不着围栏放宽档的游程（<0.8×列距），墙外扩后
# 留在图块边缘，是 vol02 wide_gap 的主要成因（抽 24 例有 19 例是
# 「字 + 贴边残条」）。清除条件全部同时成立才动手——尤其高度上限：
# 「刂/亅」这类真实的细长边缘笔画高约一个字高，残段实测 5~60px。
RESIDUE_W_MAX = 6          # 残条宽度上限（px）
RESIDUE_HW_MIN = 3.0       # 高 ≥ 此倍数 × 宽（细高形；圆点不动）
RESIDUE_H_MAX = 0.5        # 高度上限 = 此比例 × 格高（真笔画 ~0.8 格高）
RESIDUE_EDGE = 10          # 整体落在距图块左/右边缘此距离内才算贴边
RESIDUE_GAP = 3            # 与非残条墨体的横向间隔至少此值（px）
SIDE_PROBE = 12            # 向列框左右各探这么多像素，看横条是否继续
SIDE_INK_T = 0.25          # 探针带内墨量占比超此算「还在走」
OFF_CENTER_T = 0.15
# ── 夹注/双行小字（列上下文判据）──────────────────────────
# 单格几何分不开「夹注行」与「左右结构字」（真夹注 span 0.99~1.0 vs 单字
# 0.60~0.70 是唯一不重叠的量，但保险起见还要列上下文）：夹注是**列区域**
# 现象，连续多格都有双列形态、且缝的 x 位置对齐；散在的左右结构字对不齐。
JIAZHU_SPAN_T = 0.85       # 两个子列合起来占列宽的比例下限（单字只占 ~0.7）
JIAZHU_GAP_MIN = 3         # 子列间缝宽下限（px）。部首缝只有 2~3px
JIAZHU_MASS_W = 0.6        # 单个子列宽度上限（× 列宽）
JIAZHU_ALIGN = 8           # 相邻格的缝中心相差不超过此才算同一条夹注（px）
JIAZHU_MIN_RUN = 2         # 至少连续这么多格才判夹注        # 墨的横向重心偏离格心超此比例 → 疑似横向截断
                           # 标注集里 clean 最大 0.088、truncated 0.148~0.339；
                           # 全书命中 3.4%(vol01)/1.4%(vol02)，目视 15/18 属实

# 灰度源目录解析顺序：越靠前的越接近原始灰度（信息保留最多）。
# 注意：只有与 Phase 2/3 检测坐标系同尺寸的步骤才能入选
# （s3_crop 裁剪之后的步骤同尺寸；s4_enhance_lines 有画线增强，不作字形源）。
SOURCE_DIR_CANDIDATES = ("s5_split", "s4_deskew", "s3_crop", "s6_binarize")


@dataclass
class CharInstance:
    """单字实例元数据（index.jsonl 的一行）。"""
    id: str
    book: str
    page: str
    col: int
    idx: int
    bbox: tuple[float, float, float, float]   # 页面坐标 (x0, y0, x1, y1)，含 padding
    cell_type: str                            # "char"
    ocr_text: str | None                      # Phase3 整列 OCR 对位字（弱先验）
    ocr_confidence: float
    patch_path: str                           # 相对 phase4_chars/ 的路径
    ink_ratio: float
    height: float                             # bbox 高（不含 padding）
    width: float
    flags: list[str]                          # ["suspect_empty", "bad_seg", ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "CharInstance":
        d = json.loads(line)
        d["bbox"] = tuple(d["bbox"])
        return cls(**d)


def _deshear(gray: np.ndarray, tan_t: float) -> np.ndarray:
    """与 grid_segment.deshear 同一变换（以纵向中点为不动点）。

    放在这里而不 import，是为了保持 extractor 不反向依赖 grid_segment
    （grid_segment 已经 import 了 extractor，反过来 import 会成环）。
    两处必须一致，改一处就要改另一处——回归测试 test_deshear_matches
    钉住这一点。
    """
    if not tan_t:
        return gray
    h, w = gray.shape[:2]
    m = np.float32([[1, -tan_t, tan_t * h / 2], [0, 1, 0]])
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def _defect_features(gray: np.ndarray) -> dict:
    """按**缺陷形状**分开度量，而不是把所有毛病压成一个墨量比例。

    为什么要拆开
    ------------
    `_boundary_ink_frac` 是个笼统的量：界行竖线贯穿全高会在边缘带留墨，
    可**顶天立地的高字**同样会。实测 70 个人工标注图块，单靠它是
    召回 88% / 误报 10%；把缺陷按形状拆成三个判据后，**确定层做到
    召回 71% 且零误报**，剩下的才交给笼统判据兜底。

    三个确定层判据（各自对应一种物理成因）：

    - `rule_bar`   细长、近乎满高的**独立**连通体 → 界行/版框竖线混入。
                   位置**不限**于图块边缘：实测混入的竖线 x/W 从 0.08 到
                   0.96 都有（版心宽度与切分相位共同决定），限定「贴边」
                   反而漏掉一半。汉字里没有哪个**独立**部件既满格高又
                   这么细——满高的竖笔总是连在字身上的。
    - `edge_blob`  连通体**整体**落在上/下边缘带内 → 上下邻字残余。
                   注意是「整体落在带内」，不是「有墨落在带内」：后者
                   会把高字一起冤枉。
    - `frame_bars` 近乎满宽的扁横条 **≥2 条** → 版框横线，整块不是字。
                   为什么要数到 2：单条满宽扁横条就是「一」字本身，实测
                   5 个 clean 的「一」都被旧的 rule_like 判据冤枉；版框
                   则总是成对出现（上下框线 / 文武双边）。

    疑似层（有误报，只用于送人工审查）：

    - `x_gap`      主体之间的最大水平空隙 → 疑似把两列的墨切进了同一块。
    """
    out = {"rule_bar": 0.0, "edge_blob": 0.0, "frame_bars": 0, "x_gap": 0.0}
    if gray.size == 0:
        return out
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = (gray < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    total = int(binary.sum())
    if total == 0:
        return out
    h, w = binary.shape
    band = max(2, int(h * DEFECT_BAND))
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    # 本字主体 = 最大连通体；带内块要与它隔开足够远才算邻字残余
    main = int(np.argmax(stats[1:, 4])) + 1 if n > 1 else 0
    m_y0 = int(stats[main][1]) if main else 0
    m_y1 = m_y0 + int(stats[main][3]) if main else h
    spans: list[tuple[int, int]] = []
    for k, (cx, cy, cw, ch, area) in enumerate(stats[1:], start=1):
        frac = area / total
        if ch >= RULE_BAR_H * h and cw <= RULE_BAR_W * w:
            out["rule_bar"] = max(out["rule_bar"], frac)
        gap = (m_y0 - (cy + ch)) if cy + ch <= band else (cy - m_y1)
        if k != main and (cy + ch <= band or cy >= h - band) \
                and gap > EDGE_BLOB_GAP * h:
            out["edge_blob"] = max(out["edge_blob"], frac)
        if cw >= FRAME_BAR_W * w and ch <= FRAME_BAR_H * h and frac >= 0.02:
            out["frame_bars"] += 1
        if frac >= MIN_SPAN_INK:
            spans.append((int(cx), int(cx + cw)))
    if len(spans) > 1:
        spans.sort()
        gap, reach = 0, spans[0][1]
        for s0, s1 in spans[1:]:
            gap = max(gap, s0 - reach)
            reach = max(reach, s1)
        out["x_gap"] = gap / w
    return out


def _bar_crosses_column(page: np.ndarray, patch: np.ndarray,
                        x0: int, x1: int, y0: int) -> bool:
    """图块里的满宽扁横条是否**越出列外继续走**——那就是版框/界行横线。

    单条满宽扁横条本身分不清是版框横线还是「一」字：形状一模一样
    （实测两者的 w/W、h/H、厚度变异都重叠）。真正的区别在列**之外**：
    版框横线横穿整版，「一」字停在本列文字带里。所以判据只能到页级去
    取证——看同一批行在列框左右两侧还有没有墨。
    """
    if page.size == 0 or patch.size == 0:
        return False
    ph, pw = patch.shape[:2]
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    total = max(1, int(binary.sum()))
    for i in range(1, n):
        cx, cy, cw, ch, area = stats[i]
        if not (cw >= FRAME_BAR_W * pw and ch <= FRAME_BAR_H * ph
                and area >= 0.02 * total):
            continue
        rows = slice(y0 + cy, y0 + cy + ch)
        left = page[rows, max(0, x0 - SIDE_PROBE):max(0, x0)]
        right = page[rows, min(page.shape[1], x1):
                     min(page.shape[1], x1 + SIDE_PROBE)]
        if left.size == 0 or right.size == 0:
            continue
        lo = (left < BINARY_THRESHOLD_PATCH).mean()
        ro = (right < BINARY_THRESHOLD_PATCH).mean()
        if lo > SIDE_INK_T and ro > SIDE_INK_T:
            return True          # 左右都还在走 → 横穿整版
    return False


def _off_center_frac(gray: np.ndarray) -> float:
    """墨的**横向重心**偏离格心的比例 —— 横向截断的判据。

    为什么用重心而不是边缘墨量：`boundary_ink` 只看上下带，抓得到纵向
    截断；横向被切时字整个被推到格位一侧，边缘墨量未必高，但重心明显偏。
    实测标注集里 clean 的偏移最大 0.088，横向截断的 6 个实例是
    0.148~0.339，没有重叠。

    局限：空格位里若只剩一小块残墨，重心也会偏——那类由 suspect_empty /
    frame_bars 覆盖，本判据只放在**疑似层**，不单独下结论。
    """
    if gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = gray < BINARY_THRESHOLD_PATCH
    cols = np.nonzero(binary.any(axis=0))[0]
    if len(cols) == 0:
        return 0.0
    w = binary.shape[1]
    return float(abs(cols.mean() - w / 2) / w)


def _defect_flags(gray: np.ndarray) -> list[str]:
    """图块缺陷自检，分「确定」「疑似」两层输出 flag。

    确定层（rule_bar / edge_blob / frame_bars）实测零误报，下游可以直接
    按成因自动处理；疑似层（wide_gap / boundary_ink）会误报，只用来把
    图块送进人工审查队列。两层合起来实测召回 100%、误报 14%
    （67 个人工标注图块；对照：单用 boundary_ink 是 88% / 10%）。
    """
    f = _defect_features(gray)
    flags: list[str] = []
    if f["rule_bar"] > RULE_BAR_INK:
        flags.append("rule_bar")            # 混入界行/版框竖线
    if f["edge_blob"] > EDGE_BLOB_INK:
        flags.append("edge_blob")           # 上下邻字残余
    if f["frame_bars"] >= FRAME_BAR_N:
        flags.append("frame_bars")          # 版框横线，非文字
    if f["x_gap"] > WIDE_GAP_T:
        flags.append("wide_gap")            # 疑似跨列
    if _off_center_frac(gray) > OFF_CENTER_T:
        flags.append("off_center")          # 疑似横向截断
    if _boundary_ink_frac(gray) > BOUNDARY_INK_T:
        flags.append("boundary_ink")        # 疑似：边缘带见墨
    return flags



def _jiazhu_gap_center(gray: np.ndarray) -> float | None:
    """图块若呈「双列小字」形态，返回两子列之间缝的中心 x；否则 None。

    判据（实测 vol02 版本注「永樂大典本/通志堂本」与 vol01 职名双行结衔）：
    墨的总跨度占满列宽（span ≥ JIAZHU_SPAN_T——夹注两个子列合起来和正文
    一样宽，单字只占 ~0.7）、中缝 ≥ JIAZHU_GAP_MIN px（部首缝只有 2~3px）、
    两侧墨量均衡、单侧不超过 0.6 列宽。

    单格判据仍会被个别字骗到，所以**必须配合列上下文**使用：只有连续
    JIAZHU_MIN_RUN 格以上、缝中心对齐（±JIAZHU_ALIGN px）才落 jiazhu flag
    ——图块按列条带裁、x 坐标同系，缝中心可直接比较。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = (gray < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    h, w = binary.shape
    if binary.sum() < 80:
        return None
    xp = binary.sum(axis=0)
    ink = np.flatnonzero(xp > 0)
    if len(ink) < 10:
        return None
    x0, x1 = int(ink[0]), int(ink[-1])
    if (x1 - x0 + 1) / w < JIAZHU_SPAN_T:
        return None
    runs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(xp[x0:x1 + 1]):
        if v == 0 and start is None:
            start = i
        elif v > 0 and start is not None:
            runs.append((start, i)); start = None
    gaps = [(a, b) for a, b in runs
            if x0 + a > w * 0.30 and x0 + b < w * 0.70
            and b - a >= JIAZHU_GAP_MIN]
    if not gaps:
        return None
    ga, gb = max(gaps, key=lambda r: r[1] - r[0])
    left = binary[:, x0:x0 + ga]
    right = binary[:, x0 + gb:x1 + 1]
    if min(int(left.sum()), int(right.sum())) < 40:
        return None
    if min(left.sum(), right.sum()) / max(left.sum(), right.sum()) < 0.25:
        return None
    if max(left.shape[1], right.shape[1]) > JIAZHU_MASS_W * w:
        return None
    return float(x0 + (ga + gb) / 2)


def flag_jiazhu_runs(entries: list[tuple[int, float | None]]) -> set[int]:
    """列内连续、缝对齐的夹注格序号集合。entries: [(idx, gap_center|None)]。"""
    out: set[int] = set()
    run: list[int] = []
    prev_i = prev_c = None
    for i, c in sorted(entries):
        ok = (c is not None and prev_i is not None and i == prev_i + 1
              and prev_c is not None and abs(c - prev_c) <= JIAZHU_ALIGN)
        if ok:
            run.append(i)
        else:
            if len(run) >= JIAZHU_MIN_RUN:
                out.update(run)
            run = [i] if c is not None else []
        prev_i, prev_c = i, c
    if len(run) >= JIAZHU_MIN_RUN:
        out.update(run)
    return out

def _boundary_ink_frac(gray: np.ndarray) -> float:
    """图块**上下边缘带**的墨量占全图块墨量的比例。

    干净的字整个待在格内、上下留白，边缘带几乎没墨（实测 clean 图块
    该值中位数为 0.000）；一旦上下邻字的残余探进来，或本字自己被切在
    边界上，边缘带就会见墨。因此这一个量同时是「混入」与「截断」的
    线索——两者都表现为墨顶到了边界。

    关键性质：**对多裁空白免疫**。多留白只会把边缘带推得离字更远、
    该值更接近 0，绝不会误报。判定切分质量只能看墨不能看框，这个量
    正是按墨算的。

    实测（70 个人工标注图块，留一交叉验证 F1 0.682 / 召回 0.65，
    对照原先三个 flag 的缺陷召回 0.12）：单独用它就够，再叠加「边缘
    竖线覆盖率」没有增益——界行贯穿全高，本来就会在边缘带留墨。
    """
    if gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = gray < BINARY_THRESHOLD_PATCH
    total = int(binary.sum())
    if total == 0:
        return 0.0
    band = max(2, int(binary.shape[0] * BOUNDARY_BAND))
    edge = int(binary[:band].sum()) + int(binary[-band:].sum())
    return edge / total


def strip_rule_residue(patch: np.ndarray, cell_h: float) -> np.ndarray:
    """抹掉最外侧的界行残条（磨损界行断成的短竖段/虚线链）。

    按 x **跨段**（被 ≥RESIDUE_GAP 空白列隔开的墨列组）处理，而不是按
    连通体——虚线链是多个小连通体但同属一个窄跨段。最外侧跨段满足：
    窄（≤RESIDUE_W_MAX）、段内最长连续竖游程 ≤RESIDUE_H_MAX×格高
    （「刂/亅」等真实边缘长笔画是 0.7~0.9 格高的**连续**竖线，不会中招）、
    墨量 ≤20% —— 整段抹白。每侧最多剥两层（残条+毛点可能成两段）。
    抹的是像素不是 flag：残条同时也污染聚类，清源比压报警对。"""
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    total = int(binary.sum())
    if total < 1:
        return patch
    colink = binary.sum(axis=0)
    W = len(colink)

    def spans() -> list[tuple[int, int]]:
        out, s = [], None
        gap = 0
        for x in range(W):
            if colink[x] > 0:
                if s is None:
                    s = x
                gap = 0
            elif s is not None:
                gap += 1
                if gap >= RESIDUE_GAP:
                    out.append((s, x - gap + 1))
                    s = None
        if s is not None:
            out.append((s, W))
        return out

    def is_residue(a: int, b: int) -> bool:
        if b - a > RESIDUE_W_MAX:
            return False
        seg = binary[:, a:b]
        if seg.sum() > 0.2 * total:
            return False
        rows = seg.any(axis=1)
        run = mx = 0
        for v in rows:
            run = run + 1 if v else 0
            mx = max(mx, run)
        if mx <= RESIDUE_H_MAX * cell_h:
            return True
        # 更长的残段（实测有 78px 的，几乎够着「刂」的 0.7 格）只在
        # 图块最外 12% 宽度内才认——字的笔画到不了那里（图块按墙裁、
        # 字居中，字缘距边 ≥15%），残条恰恰贴着墙根
        edge = 0.12 * W
        return (mx <= 0.85 * cell_h
                and (b <= edge or a >= W - edge))

    out = patch
    for _ in range(2):
        sp = spans()
        if len(sp) < 2:          # 只剩一个跨段：那是 rule_bar/not_text 的事
            break
        hit = False
        edge_spans = [sp[0]] if sp[0] == sp[-1] else [sp[0], sp[-1]]
        for a, b in edge_spans:
            if is_residue(a, b):
                if out is patch:
                    out = patch.copy()
                out[:, a:b] = 255
                binary[:, a:b] = 0
                colink[a:b] = 0
                hit = True
        if not hit:
            break
    return out


def _patch_ink_ratio(gray: np.ndarray) -> float:
    """Otsu 二值化后的暗像素占比（粗略墨迹密度，供分块与异常过滤）。"""
    if gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return float(np.count_nonzero(binary)) / binary.size



# ── 列级连通体归属（避免边框与邻字残余混入）──────────────

MIN_COMP_AREA_RATIO = 0.004   # 连通体面积 < 格面积此比例 → 噪点，丢弃
RULE_H_RATIO = 1.6            # 高 > 此倍格高 且窄 → 界行竖线
RULE_W_RATIO = 0.18           # 界行宽度上限（× 列宽）
MERGE_H_RATIO = 1.45          # 连通体高于此倍格高 → 粘连块，回退按格线切
SPLIT_H_RATIO = 1.05          # 连通体高于此倍格高 → 必然跨格线，试着在「颈部」切开
SPLIT_WIN = 0.16              # 颈部搜索窗（× 格高，格线上下各此范围）
NECK_ABS = 0.30               # 颈部墨宽绝对上限（× 列宽）
MIN_PIECE = 0.50              # 切开后上半块的最小高度（× 格高）
MIN_TAIL = 0.10               # 切开后下半块的最小高度（× 格高）
MAX_ATTACH = 0.45             # 零散部件与字身的最大纵向间隙（× 格高）
FIT_RATIO = 1.15              # 部件并入字身后的总高上限（× 格高）——刻本单字装得下格
MAX_EXTEND_RATIO = 0.35       # 图块最多比格位多裁这么多（× 格高），防粘连失控
HALO_DILATE = 2               # 抹除非本格墨迹时一并抹掉的灰边（px）


def _column_binary(col_gray: np.ndarray) -> np.ndarray:
    """列内二值化。Otsu 阈值加夹取——整列全空时 Otsu 会把纸纹判成墨。"""
    thr, binary = cv2.threshold(col_gray, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if not (60 <= thr <= 180) or np.count_nonzero(binary) > 0.6 * binary.size:
        binary = (col_gray < 128).astype(np.uint8) * 255
    return (binary > 0).astype(np.uint8)


RULE_BAND_COVER = 0.90        # 窗口内某 x 列的墨迹纵向覆盖率超此 → 界行所在列
BORDER_LINE_COVER = 0.92      # 连通体宽度占列宽超此 且极扁 → 版框横线
BORDER_LINE_H = 0.05          # 版框横线高度上限（× 格高）
BORDER_EDGE_BAND = 0.10       # 只在条带上下这么大范围内认版框横线
LINE_WIN_CELLS = 2.0          # 竖线检测滑窗高度（× 格高）
LINE_SCOPE_CELLS = 2.5        # 条带至少这么多格高才做整条线剔除（防误杀单字竖笔）


def _strip_lines(binary: np.ndarray, cell_h: float) -> np.ndarray:
    """从列条带里剔除界行竖线与版框横线所占的像素带。

    必须在连通体分析**之前**做：笔画一旦碰到界行，二者就是同一个连通
    体，「高且窄」判据当场失效，整条线会被当成粘连块按格硬切、混进每
    一格——实测这正是净化率上不去的主因。

    投影要**分窗做**，不能整条列一次投影：残余倾斜下一条界行在 2000px
    的列高上会横移好几像素，整列投影一摊平，没有任何一个 x 列的覆盖率
    还够得着阈值（实测整列投影只清掉了 20% 的界行残留）。滑窗取 2 倍
    格高——足够长到单字竖笔（最多一格高）永远够不着 90% 覆盖，又足够短
    到界行在窗内近似垂直。

    **不做横行投影**：版框横线固然是「整行满墨」，但「宀」「一」「書」
    顶横这类笔画同样能占满整个列宽——实测按横行投影剔除会把「守」削成
    「寸」、把「書」削掉顶横。版框横线改在连通体层面按「贴条带上下端 +
    极扁 + 满宽」三条同时成立才丢（见 _assign_column）。
    """
    h, w = binary.shape
    if h < LINE_SCOPE_CELLS * cell_h:
        return binary
    out = binary.copy()
    win = max(2, int(round(LINE_WIN_CELLS * cell_h)))
    step = max(1, win // 2)
    for y0 in range(0, h, step):
        y1 = min(h, y0 + win)
        if y1 - y0 < win // 2:
            break
        seg = binary[y0:y1]
        cols = seg.sum(axis=0) / float(y1 - y0)
        hit = cols >= RULE_BAND_COVER
        if hit.any() and int(hit.sum()) <= max(2, RULE_W_RATIO * w):
            out[y0:y1, hit] = 0
    return out


def _split_touching(binary: np.ndarray,
                    cells: list[tuple[int, float, float]],
                    cell_h: float, col_w: float) -> np.ndarray:
    """把上下相邻两字**粘在一起**的连通体在颈部切开。

    实测最难缠的一类：上一字的长竖（如「草」的「早」竖）拖到格线下面，
    正好压在下一字的宀上，两字连成一体。此时归属算法只能整块判给其中
    一格，另一格就凭空少一整个部首——不是判错，是根本没得判。

    按格线硬切会把上一字的竖尾送给下一格；改在格线附近找**墨最细的一
    行**下刀。三条约束缺一不可：

    - 颈要**够细**：墨宽细过 NECK_ABS×列宽；
    - 切完**上半块正好是一个字**（MIN_PIECE ~ FIT_RATIO 倍格高）——太矮
      说明切在了「粘着的上一字残尾」与本字之间，切下去本字反倒少一个
      部首；太高说明这刀白切，上半块还是两个字；
    - 下半块不能只剩碎渣。

    找不到合格的颈（真·重度粘连）就不切，留给后面的按格线硬切兜底。
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    out = binary.copy()
    lines = [top for _i, top, _b in cells[1:]]
    win = SPLIT_WIN * cell_h
    for k in range(1, n):
        x, y, cw, ch, _area = stats[k]
        if ch <= SPLIT_H_RATIO * cell_h:
            continue
        comp = labels == k
        prof = comp.sum(axis=1)
        for g in lines:
            lo = int(max(y + 0.2 * cell_h, g - win))
            hi = int(min(y + ch - 0.2 * cell_h, g + win,
                         y + FIT_RATIO * cell_h))
            if hi <= lo:
                continue
            thin = np.flatnonzero(prof[lo:hi] <= NECK_ABS * col_w) + lo
            # 上半块必须够得上一个字。否则会切在「粘着的上一字残尾」和
            # 本字之间——那道缝也在格线附近、也很细，切下去本字就少一个
            # 部首（实测把「草」的艹切给了上一格）。
            thin = thin[(thin - y >= MIN_PIECE * cell_h)
                        & (y + ch - thin >= MIN_TAIL * cell_h)]
            if thin.size == 0:
                continue
            # 取细颈里**离格线最近**的一行，而不是最细的一行。上一字的
            # 竖尾是一根长而匀的细杆，整段都一样细，压根没有「局部谷底」；
            # 按最细取会跑到杆子末端去切，切完上半块还是两个字。
            r = int(thin[np.argmin(np.abs(thin - g))])
            out[r:r + 2][comp[r:r + 2]] = 0    # 切两行，断开 8 连通
    return out


def _assign_column(col_gray: np.ndarray,
                   cells: list[tuple[int, float, float]],
                   cell_h: float, col_w: float
                   ) -> tuple[dict[int, tuple[int, int, int, int]], np.ndarray]:
    """列内连通体按格位归属。

    返回 (boxes, owner)：
      boxes  {格序号: (x0,y0,x1,y1)} 该格所属墨迹的外接框（列内局部坐标）
      owner  与 col_gray 同形，0 = 背景/丢弃，格序号+1 = 归属该格

    **先定字身，再就近投靠**：

    1. 界行竖线（分窗投影）与版框横线先整体剔除，它们跨格且无归属；
       上下两字粘成一体的连通体在颈部切开（见 _split_touching）；
    2. 每格取「与该格行区间重叠最多、且自身多半落在格内」的连通体作
       **字身**，贪心最大重叠匹配，一格一个、一块只当一次；
    3. 其余零散部件不看格线，按四级键选字身：
       装得下（并入后 ≤FIT_RATIO 倍格高）→ 越格量（并入后越出该格格线
       的量）→ 间隙（有交叠时取负）→ 横向距离。

    第 3 步是关键。刻本格高是刚性的，但字有大有小、位置略偏，「守」的
    宀、「高/卞/示」的顶点常常整个落到上一格的行区间里——只按格线判，
    这些部件会被判给上一格然后被抹掉（实测把「守」削成「寸」、「范」
    削成「氾」）。而改判间隙阈值同样不行：实测污染块与真部件的间隙分布
    （p50 10px vs 12px）**完全重叠**，任何阈值都必然误伤。四级键把判断
    换到了别的维度：**并进去之后这个字还待在自己格里吗**——归本格则整字
    仍在格内，归上一格则整字要跨出格线一大截。间隙只在前两级分不出胜负
    时才用得上，且比的是相对距离，不设任何绝对阈值。

    cells: [(格序号, y_top, y_bottom)]（列内局部坐标），拉开列的
    非均匀格位同样适用。
    """
    h = col_gray.shape[0]
    binary = _split_touching(
        _strip_lines(_column_binary(col_gray), cell_h), cells, cell_h, col_w)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    min_area = MIN_COMP_AREA_RATIO * cell_h * col_w
    owner = np.zeros(labels.shape, np.int32)
    boxes: dict[int, list[int]] = {}

    def add(idx: int, x0: int, y0: int, x1: int, y1: int) -> None:
        b = boxes.get(idx)
        if b is None:
            boxes[idx] = [x0, y0, x1, y1]
        else:
            b[0] = min(b[0], x0); b[1] = min(b[1], y0)
            b[2] = max(b[2], x1); b[3] = max(b[3], y1)

    # ── 1. 筛掉线状与噪点，分出「可归属」与「粘连块」──────
    live: dict[int, tuple[int, int, int, int, int]] = {}   # k → (x,y,w,h,area)
    merged: list[int] = []
    for k in range(1, n):
        x, y, cw, ch, area = stats[k]
        if area < min_area:
            continue
        if ch > RULE_H_RATIO * cell_h and cw <= RULE_W_RATIO * col_w:
            continue                                  # 界行/版框竖线
        if (cw >= BORDER_LINE_COVER * col_w
                and ch <= BORDER_LINE_H * cell_h
                and (y + ch <= BORDER_EDGE_BAND * h
                     or y >= (1 - BORDER_EDGE_BAND) * h)):
            continue                                  # 版框横线（仅认条带两端）
        if ch > MERGE_H_RATIO * cell_h:
            merged.append(k)
            continue
        live[k] = (int(x), int(y), int(cw), int(ch), int(area))

    cell_span = {i: (top, bot) for i, top, bot in cells}

    def rows_in(k: int, top: float, bot: float) -> int:
        x, y, cw, ch, _a = live[k]
        return max(0, min(y + ch, int(bot)) - max(y, int(top)))

    # ── 2. 每格认一个字身（一个连通体只当一次字身）──────
    # 贪心最大重叠匹配：一个格一个字身、一个连通体只当一次字身。
    # 逐格取最优会漏配——某块被隔壁以更大重叠抢走后，本格就再没有第二
    # 选择，整格没了字身，零散部件只好去投靠隔壁，连锁错到底。
    pairs = []
    for i, top, bot in cells:
        for k in live:
            ov = rows_in(k, top, bot)
            if ov > 0 and ov >= 0.3 * live[k][3]:     # 多半在格内才够格当字身
                pairs.append((ov, i, k))
    pairs.sort(key=lambda t: -t[0])
    claim: dict[int, int] = {}                        # k → 格序号
    taken_cell: set[int] = set()
    for _ov, i, k in pairs:
        if i in taken_cell or k in claim:
            continue
        claim[k] = i
        taken_cell.add(i)
    bodies: dict[int, tuple[int, int, int, int]] = {}  # 格序号 → 字身框
    for k, i in claim.items():
        x, y, cw, ch, _a = live[k]
        owner[labels == k] = i + 1
        add(i, x, y, x + cw, y + ch)
        bodies[i] = (x, y, x + cw, y + ch)

    # ── 3. 零散部件就近投靠字身 ────────────────────────
    for k in live:
        if k in claim:
            continue
        x, y, cw, ch, _a = live[k]
        cx = x + cw / 2
        best, best_key = None, None
        for i, (bx0, by0, bx1, by1) in bodies.items():
            top, bot = cell_span[i]
            u0, u1 = min(by0, y), max(by1, y + ch)
            # 并入后**越出该格格线**的量。刻本单字待在自己格里，这一条
            # 把「顶部部件该归谁」从模棱两可的距离比较变成了确定判断：
            # 归本格则整字仍在格内，归上一格则整字要跨出格线一大截。
            excess = round((max(0.0, top - u0) + max(0.0, u1 - bot))
                           / cell_h, 2)
            # 先看「并进去还装得下一格吗」。刻本单字必然装得进格高，所以
            # 并入后总高爆掉的那个字身一定不是它的归属——「字」的宀同时
            # 压在上一字与本字的行区间里，光比距离必然判错（实测把「字」
            # 削成「十」、「范」削成「氾」），加上这条就唯一了。
            fit = 0 if u1 - u0 <= FIT_RATIO * cell_h else 1
            # 有交叠时取负值（交叠越多越"近"）。截到 0 的话，一个纵向同时
            # 压到两个字身的部件会两边都算 0，只能靠横向距离瞎猜——实测
            # 「廁」的左右两竖就是这样被判给了下一格。
            gap = max(by0 - (y + ch), y - by1)
            key = (fit, excess, gap, abs(cx - (bx0 + bx1) / 2))
            if best_key is None or key < best_key:
                best, best_key = i, key
        if best is None or best_key[2] > MAX_ATTACH * cell_h:
            best, best_ov = None, 0                   # 无字身可投 → 退回按格线
            for i, top, bot in cells:
                ov = rows_in(k, top, bot)
                if ov > best_ov:
                    best, best_ov = i, ov
            if best is None:
                continue
        owner[labels == k] = best + 1
        add(best, x, y, x + cw, y + ch)

    # ── 4. 粘连块无从归属，按格界硬切 ──────────────────
    for k in merged:
        comp = labels == k
        for i, top, bot in cells:
            t, b = max(0, int(top)), min(h, int(bot))
            if b <= t:
                continue
            sub = comp[t:b]
            if int(sub.sum()) < min_area:
                continue
            ys, xs = np.nonzero(sub)
            owner[t:b][sub] = i + 1
            add(i, int(xs.min()), t + int(ys.min()),
                int(xs.max()) + 1, t + int(ys.max()) + 1)

    return {i: tuple(b) for i, b in boxes.items()}, owner


def assign_components(col_gray: np.ndarray,
                      cells: list[tuple[int, float, float]],
                      cell_h: float, col_w: float
                      ) -> dict[int, tuple[int, int, int, int]]:
    """列内连通体归属的外接框（详见 :func:`_assign_column`）。"""
    return _assign_column(col_gray, cells, cell_h, col_w)[0]


def clean_patch(strip: np.ndarray, owner: np.ndarray, cell_idx: int,
                y0: int, y1: int) -> np.ndarray:
    """从列条带裁出一格图块，并抹掉不属于本格的墨迹（界行 / 邻字残余）。

    抹除时连灰边一起抹（膨胀 HALO_DILATE），否则反锐化的抗锯齿灰晕会
    留下一圈，归一化时仍被当成墨。抹除掩膜再减去本格墨迹，保证不啃到
    本字笔画。
    """
    patch = strip[y0:y1].copy()
    own = owner[y0:y1]
    mine = (own == cell_idx + 1).astype(np.uint8)
    other = ((own != 0) & (own != cell_idx + 1)).astype(np.uint8)
    if not other.any():
        return patch
    if HALO_DILATE > 0:
        ker = np.ones((2 * HALO_DILATE + 1, 2 * HALO_DILATE + 1), np.uint8)
        other = cv2.dilate(other, ker)
        other = other & (1 - cv2.dilate(mine, ker))
    patch[other.astype(bool)] = 255
    return patch


class CharExtractor:
    """从整页灰度图 + phase3 网格 JSON 提取单字图块。"""

    def __init__(self, padding_ratio: float = PADDING_RATIO,
                 min_ink_ratio: float = MIN_INK_RATIO,
                 strategy: str = "component_owner"):
        """strategy: 格内墨迹归属算法。

        component_owner  列级连通体归属（默认，见 _assign_column）
        padding_box      旧做法：按格线裁框 + 固定外扩，框内墨迹全收
                         （保留作对照与回滚；benchmark 里是基线）
        """
        if strategy not in ("component_owner", "padding_box"):
            raise ValueError(f"未知切分策略：{strategy}")
        self.padding_ratio = padding_ratio
        self.min_ink_ratio = min_ink_ratio
        self.strategy = strategy

    # ── 纯函数核心 ────────────────────────────────────────

    def extract_page(self, page_img: np.ndarray, grid: dict,
                     book: str, page: str
                     ) -> list[tuple[CharInstance, np.ndarray]]:
        """输入整页图 + phase3 grid JSON，输出 (实例, 图块) 列表。

        坐标系约定：grid 中的坐标即 page_img 的像素坐标
        （Phase 3 在最终预处理图上检测，本函数输入必须是同一坐标系的图）。

        切分策略：**列级连通体归属**。整列一次二值化 + 连通体分析，每块
        墨迹按「主体落在哪一格」归属；界行竖线在列级丢弃。逐格裁框时再
        把不属于本格的墨迹抹白，从根上解决左右边框混入与上下邻字残余。
        """
        if page_img.ndim == 3:
            page_img = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY)
        # grid 的坐标在**去错切帧**里。segment 把界行摆正之后才定的列，
        # 这里必须做同样的变换再裁，否则列框会整体错位；顺带图块也就
        # 跟着摆正了，对下游归一化与识别只有好处。
        shear = float(grid.get("grid", {}).get("shear", 0.0) or 0.0)
        if shear:
            page_img = _deshear(page_img, shear)
        img_h, img_w = page_img.shape[:2]
        results: list[tuple[CharInstance, np.ndarray]] = []

        for col in grid.get("columns", []):
            col_no = int(col["index"])
            left_x = float(col["left_x"])
            right_x = float(col["right_x"])
            col_w = right_x - left_x

            cells = [c for c in col.get("cells", []) if c.get("type") == "char"]
            if not cells:
                continue
            heights = [float(c["y_bottom"]) - float(c["y_top"]) for c in cells]
            cell_h_ref = float(np.median(heights))

            # 条带按切分给出的**裁切边**裁，不按文字带裁。文字带是「正常居中
            # 字」的范围，而职名列的「臣」是小字、贴着界行写：横向中心在列格
            # 的 0.78 处、只占 0.43 列宽，右缘越出文字带中位 15px（最多 31px）。
            # 按文字带裁会把它切掉——这类横向截断占标注集里截断实例的一半。
            # 裁切边由 grid_segment.cell_bounds_from_rules 逐条按实测界行定：
            # 量到界行就贴着界行内缘外扩，量不到就等于文字带（即旧行为）。
            gl = col.get("cell_left_x")
            gr = col.get("cell_right_x")
            if gl is None or gr is None:          # 老的切分产物没有这两个字段
                shrink_x = min(col_w * 0.03, 4.0)
                gl, gr = left_x + shrink_x, right_x - shrink_x
            sx0 = int(round(max(0.0, float(gl))))
            sx1 = int(round(min(float(img_w), float(gr))))
            pad_y = cell_h_ref * self.padding_ratio
            sy0 = int(round(max(0.0, min(float(c["y_top"]) for c in cells) - pad_y)))
            sy1 = int(round(min(float(img_h),
                               max(float(c["y_bottom"]) for c in cells) + pad_y)))
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            strip = page_img[sy0:sy1, sx0:sx1]
            # 弯的界行：矩形裁不掉（线在不同高度处于不同 x），按切分给出的
            # **逐带裁切边**把墙外像素抹白。必须在归属之前做——弯线一旦
            # 进入连通体分析，会与字粘连或被误归属。
            bands = col.get("cell_bands")
            if bands:
                strip = strip.copy()
                for ya, yb, blx, brx in bands:
                    ra = max(0, int(round(ya)) - sy0)
                    rb = min(strip.shape[0], int(round(yb)) - sy0)
                    if rb <= ra:
                        continue
                    ca = max(0, int(round(blx)) - sx0)
                    cb = min(strip.shape[1], int(round(brx)) - sx0)
                    if ca > 0:
                        strip[ra:rb, :ca] = 255
                    if cb < strip.shape[1]:
                        strip[ra:rb, cb:] = 255

            col_entries: list[tuple[int, float | None, CharInstance]] = []
            local = [(int(c["index"]),
                      float(c["y_top"]) - sy0,
                      float(c["y_bottom"]) - sy0) for c in cells]
            if self.strategy == "component_owner":
                boxes, owner = _assign_column(strip, local, cell_h_ref,
                                              float(sx1 - sx0))
            else:
                boxes, owner = {}, None

            for cell, (idx, ltop, lbot) in zip(cells, local):
                cell_h = lbot - ltop
                pad = cell_h * self.padding_ratio
                y0 = max(0, int(round(ltop - pad)))
                y1 = min(strip.shape[0], int(round(lbot + pad)))
                box = boxes.get(idx)
                if box is not None:
                    # 归属墨迹越出格位（出头笔画 / 与邻字粘连）时按需放宽，
                    # 但不超过 MAX_EXTEND_RATIO，避免粘连块把图块撑爆。
                    lim = cell_h * MAX_EXTEND_RATIO
                    y0 = max(0, int(round(max(ltop - lim, min(y0, box[1])))))
                    y1 = min(strip.shape[0],
                             int(round(min(lbot + lim, max(y1, box[3])))))
                if y1 <= y0:
                    continue
                patch = (strip[y0:y1].copy() if owner is None
                         else clean_patch(strip, owner, idx, y0, y1))
                patch = strip_rule_residue(patch, cell_h)

                x0 = float(sx0)
                x1 = float(sx1)
                py0 = float(sy0 + y0)
                py1 = float(sy0 + y1)

                ink = _patch_ink_ratio(patch)
                flags: list[str] = []
                if (owner is not None and box is None) or ink < self.min_ink_ratio:
                    flags.append("suspect_empty")
                # 缺陷自检：确定层按成因分开标，疑似层兜底送审查。
                # 旧的 rule_like（单条满宽扁横条即报）已退休——它把 5 个
                # 干净的「一」字全判成了线，改由 frame_bars 数到 2 条才报。
                flags.extend(_defect_flags(patch))
                # 单条满宽扁横条形状上分不清版框横线与「一」字，只能到
                # 页级取证：看它在列框外还继不继续走。
                if "frame_bars" not in flags and _bar_crosses_column(
                        page_img, patch, int(x0), int(x1), int(py0)):
                    flags.append("frame_bars")
                # 切分异常提示：字块长宽比离谱（粘连/切半）
                aspect = cell_h / max(col_w, 1e-6)
                if aspect > 1.8 or aspect < 0.3:
                    flags.append("bad_seg")

                inst = CharInstance(
                    id=make_id(book, page, col_no, idx),
                    book=book, page=page, col=col_no, idx=idx,
                    bbox=(x0, py0, x1, py1),
                    cell_type="char",
                    ocr_text=cell.get("text") or None,
                    ocr_confidence=float(cell.get("confidence", 0.0)),
                    patch_path=f"patches/{page}/{col_no}_{idx}.png",
                    ink_ratio=round(ink, 4),
                    height=round(cell_h, 2),
                    width=round(col_w, 2),
                    flags=flags,
                )
                results.append((inst, patch))
                col_entries.append((idx, _jiazhu_gap_center(patch), inst))
            # 夹注/双行小字：连续 ≥2 格、缝中心对齐才落 flag（疑似层）。
            # 下游把 jiazhu 图块隔离成单例，不进簇、不进训练。
            for j in flag_jiazhu_runs([(i, c) for i, c, _ in col_entries]):
                for i, _c, inst in col_entries:
                    if i == j and "jiazhu" not in inst.flags:
                        inst.flags.append("jiazhu")
        return results

    # ── IO 壳 ────────────────────────────────────────────

    def run_book(self, book_out_dir: Path, source_dir: Path | None = None,
                 name_filter: set[str] | None = None) -> dict:
        """遍历 phase3_char_grid/*_char_grid.json，写 phase4_chars/。

        Args:
            book_out_dir: output/bookX/
            source_dir: 页面图目录；缺省时按 SOURCE_DIR_CANDIDATES 顺序解析。
        Returns:
            meta 统计 dict。
        """
        book_out_dir = Path(book_out_dir)
        book = book_out_dir.name
        grid_dir = book_out_dir / "phase3_char_grid"
        grid_files = sorted(grid_dir.glob("*_char_grid.json"))
        if name_filter is not None:
            grid_files = [f for f in grid_files
                          if f.stem.replace("_char_grid", "") in name_filter]
        if not grid_files:
            raise FileNotFoundError(f"未找到字符网格 JSON: {grid_dir}（请先运行 extract）")

        src = Path(source_dir) if source_dir else self._resolve_source_dir(book_out_dir)

        out_dir = book_out_dir / "phase4_chars"
        out_dir.mkdir(parents=True, exist_ok=True)

        n_pages = n_chars = n_flagged = 0
        # 归一化缓存：cluster 阶段要把每个图块 imread 回来再归一化
        # （实测 81s/册）；图块此刻就在内存里，顺手归一化存成 npz，
        # cluster 直接查缓存、缺了再 imread 兜底（PNG 无损，两条路
        # 逐像素等价——已实测验证）。
        norm_ids: list[str] = []
        norm_arrs: list[np.ndarray] = []
        index_path = out_dir / "index.jsonl"
        with open(index_path, "w", encoding="utf-8") as index_f:
            for gf in grid_files:
                page = gf.stem.replace("_char_grid", "")
                img_path = self._find_page_image(src, page)
                if img_path is None:
                    print(f"  跳过 {page}: 在 {src} 中找不到页面图")
                    continue
                page_img = imread(str(img_path))
                if page_img is None:
                    print(f"  跳过 {page}: 读取失败")
                    continue
                with open(gf, "r", encoding="utf-8") as f:
                    grid = json.load(f)

                # 先清空本页旧图块再写：切分改动后格数会变，残留的旧图块
                # 不在新 index.jsonl 里，却仍躺在磁盘上冒充有效实例。实测
                # 一次重跑留下 2456 个这样的孤儿，害得按 page:col:idx 对标
                # 的人工标签对上了**过期图块**，测出自相矛盾的报告。
                page_patch_dir = out_dir / "patches" / page
                if page_patch_dir.exists():
                    for stale in page_patch_dir.glob("*.png"):
                        stale.unlink()
                page_patch_dir.mkdir(parents=True, exist_ok=True)
                for inst, patch in self.extract_page(page_img, grid, book, page):
                    imwrite(str(out_dir / inst.patch_path), patch)
                    index_f.write(inst.to_json() + "\n")
                    norm_ids.append(inst.patch_path)
                    norm_arrs.append(normalize_patch(patch))
                    n_chars += 1
                    if inst.flags:
                        n_flagged += 1
                n_pages += 1

        np.savez_compressed(
            out_dir / "normalized.npz",
            ids=np.array(norm_ids),
            patches=(np.stack(norm_arrs) if norm_arrs
                     else np.zeros((0, NORM_SIZE, NORM_SIZE), dtype=np.uint8)),
            norm_size=np.int64(NORM_SIZE))

        meta = {
            "book": book,
            "source_dir": str(src),
            "params": {"padding_ratio": self.padding_ratio,
                       "min_ink_ratio": self.min_ink_ratio},
            "stats": {"pages": n_pages, "chars": n_chars, "flagged": n_flagged},
        }
        with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    @staticmethod
    def _resolve_source_dir(book_out_dir: Path) -> Path:
        for name in SOURCE_DIR_CANDIDATES:
            d = book_out_dir / name
            if d.is_dir() and any(f for ext in ("*.png", "*.tif", "*.tiff")
                                  for f in d.glob(ext)):
                return d
        # 兜底：预处理用了 --clean 时最终图直接在书目录下
        if any(f for ext in ("*.png", "*.tif", "*.tiff")
               for f in book_out_dir.glob(ext)):
            return book_out_dir
        raise FileNotFoundError(
            f"未找到页面图目录（尝试了 {SOURCE_DIR_CANDIDATES}），"
            f"请用 --input-dir 指定: {book_out_dir}")

    @staticmethod
    def _find_page_image(src: Path, page: str) -> Path | None:
        for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
            p = src / f"{page}{ext}"
            if p.exists():
                return p
        return None


def load_index(phase4_dir: Path) -> list[CharInstance]:
    """读取 phase4_chars/index.jsonl。"""
    path = Path(phase4_dir) / "index.jsonl"
    with open(path, "r", encoding="utf-8") as f:
        return [CharInstance.from_json(line) for line in f if line.strip()]
