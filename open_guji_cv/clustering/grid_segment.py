"""刻本严格网格切分（Phase 3 的替代实现，无 OCR 依赖）。

刻本古籍格式非常固定：每行严格 N 字、字高一致。据此把切分建模为
**网格拟合**而非自由投影分割：

1. 每列先验网格：[col_top, col_bottom] 均分为 N 格；
2. 全局微调：搜索 (偏移 δ, 伸缩 s)，使网格线尽量落在投影谷（字间空隙）；
3. 逐线微调：每条网格线在 ±search_ratio 格高内移到最近的投影谷，
   保持单调、格高不塌缩；
4. 格内判空：墨迹覆盖率 < empty_ink_ratio 的格为 empty。

断笔/磨损不会破坏切分——网格由整列证据共同决定，单字残损只影响该格判空。
输出与 CharGridDetector 相同的 char_grid JSON 契约，下游（M1 提取）无感。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread
from .extractor import CharExtractor

BINARY_THRESHOLD = 128
EMPTY_INK_RATIO = 0.02     # 格内墨迹覆盖率低于此 → empty
MIN_COL_WIDTH_RATIO = 0.5  # 列宽低于中位列宽的此比例 → 非文字列（版心/界行缝），跳过
SEARCH_RATIO = 0.3         # 逐线微调搜索半径（× 格高）
CELL_H_TOL = 0.05          # 页格高偏离全书共识超此比例 → 判定锁错，强制重拟
                           # （修复后自然抖动 σ≈2.2%，0.10 曾放过 0.91 的漏网页）
STRADDLE_OK = 0.50         # 骑线比（格线墨/格心墨）高于此 → 尝试相位重扫
STRADDLE_GAIN = 0.10       # 重扫至少好这么多才接受（never-make-worse）
SCALES = np.linspace(0.96, 1.04, 9)


@dataclass
class GridParams:
    chars_per_line: int
    empty_ink_ratio: float = EMPTY_INK_RATIO
    search_ratio: float = SEARCH_RATIO


def column_projection(col_gray: np.ndarray,
                      line_frac: float = 0.3) -> np.ndarray:
    """列区域的水平投影（每行黑像素数）。输入灰度或二值图。

    先用竖直开运算剔除长竖线（边框/界行残留：连续贯穿 ≥ line_frac×列高；
    字的竖笔最长 ~1 字高，绝不会被误剔）——竖线给每行加常量偏置，
    会把字间谷填平，淹没网格拟合的相位信号。只减线像素，同 x 的文字保留。"""
    binary = (col_gray < BINARY_THRESHOLD).astype(np.uint8)
    k = max(3, int(binary.shape[0] * line_frac))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k))
    vlines = cv2.dilate(cv2.erode(binary, kernel), kernel)
    cleaned = binary & (1 - vlines)
    return cleaned.sum(axis=1).astype(np.float64)


def content_range(proj: np.ndarray, rel_thresh: float = 0.05,
                  min_run: float = 0.0,
                  max_fill: float | None = None) -> tuple[int, int]:
    """投影的实际内容范围 [top, bottom)。

    版面检测的 inner_frame 常有偏差（裁进空白或裁掉首末字），网格必须
    摊在文字实际占据的范围上，否则整体相位偏移。

    min_run > 0 时，首尾的**短游程**（连续非零段长 < min_run）被忽略——
    边框横线（3~10 行）和贴边残迹是短游程，文字块是 ~字高 的长游程；
    比"单行接近满宽"判据稳健（"一"类横笔也能占满列宽，但它属于长游程）。
    空投影返回全范围。
    """
    if proj.max() <= 0:
        return 0, len(proj)
    # 参考值用非零 90 分位而非 max —— max 会被边框线尖峰抬高，
    # 连带阈值过高/过低都失真
    ref = float(np.percentile(proj[proj > 0], 90))
    mask = proj > max(ref * rel_thresh, 1.0)
    idx = np.nonzero(mask)[0]
    if min_run <= 1:
        return int(idx[0]), int(idx[-1]) + 1
    # 游程分解
    splits = np.nonzero(np.diff(idx) > 1)[0]
    starts = np.concatenate([[idx[0]], idx[splits + 1]])
    ends = np.concatenate([idx[splits] + 1, [idx[-1] + 1]])
    runs = [(int(s), int(e)) for s, e in zip(starts, ends)]

    def _is_junk(run: tuple[int, int]) -> bool:
        s, e = run
        if e - s < min_run:
            return True   # 短游程：边框线/贴边残迹
        if max_fill is not None and float(np.median(proj[s:e])) > max_fill:
            return True   # 近满宽实心块：扫描黑边/粗边框，文字远达不到
        return False

    while len(runs) > 1 and _is_junk(runs[0]):
        runs.pop(0)
    while len(runs) > 1 and _is_junk(runs[-1]):
        runs.pop()
    return runs[0][0], runs[-1][1]


def fit_global_grid(proj: np.ndarray, n_chars: int,
                    scales: np.ndarray = SCALES,
                    full_width: float | None = None) -> tuple[float, float]:
    """全局网格拟合：搜索 (偏移 δ, 伸缩 s) 使网格线落在投影谷、
    格中心落在投影峰。

    cost = mean(proj[网格线]) − 0.5 · mean(proj[格中心])
    —— 排版紧凑、谷很浅时，峰项仍提供可靠的相位信息。
    网格严格限制在内容范围内（不允许线出界"作弊"降 cost）。

    Returns:
        (offset, cell_h): 首线位置与格高（proj 坐标系）。
    """
    L = len(proj)
    top, bottom = content_range(
        proj, min_run=0.25 * L / n_chars,
        max_fill=0.9 * full_width if full_width else None)
    span_max = bottom - top
    base_h = span_max / n_chars
    smooth = _smooth(proj, base_h)

    best = (float(top), base_h)
    best_cost = float("inf")
    for s in scales:
        cell_h = base_h * s
        span = cell_h * n_chars
        max_off = span_max - span
        if max_off < -1e-6:      # 网格比内容还长：不合法
            continue
        offsets = top + np.linspace(0.0, max(0.0, max_off), num=15)
        for off in offsets:
            cost = _grid_cost(smooth, off, cell_h, n_chars)
            if cost < best_cost:
                best_cost = cost
                best = (float(off), float(cell_h))
    return best


def _smooth(proj: np.ndarray, cell_h: float) -> np.ndarray:
    kernel = max(3, int(cell_h * 0.08)) | 1
    return np.convolve(proj, np.ones(kernel) / kernel, mode="same")


def _grid_cost(smooth: np.ndarray, off: float, cell_h: float,
               n_chars: int) -> float:
    """网格代价：线落谷（小） − 0.5×格中心落峰（大）。"""
    L = len(smooth)
    li = np.clip(np.round(off + cell_h * np.arange(n_chars + 1)).astype(int),
                 0, L - 1)
    ci = np.clip(np.round(off + cell_h * (np.arange(n_chars) + 0.5)).astype(int),
                 0, L - 1)
    return float(smooth[li].mean()) - 0.5 * float(smooth[ci].mean())


def page_column_projection(gray: np.ndarray, line_frac: float = 0.3,
                           return_rule_xs: bool = False):
    """整页垂直投影（每 x 的黑像素数），供列网格拟合。

    先剔两类长线：竖直长线（界行/边框竖线——它们在垂直投影上是假峰，
    恰好位于列边界处）与水平长线（边框横线——给每 x 加常量偏置）。
    剔完后投影呈现纯净的周期结构：文字列=台地、列间缝=谷，
    与行方向的字/空隙结构同构，谷/峰代价模型可直接复用。

    return_rule_xs=True 时额外返回界行/边框竖线所在的 x 布尔掩码
    ——供列拟合质量评估（界行应落在列格之间，落入列内即拟合失败）。"""
    binary = (gray < BINARY_THRESHOLD).astype(np.uint8)
    h, w = binary.shape
    kv = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(3, int(h * line_frac))))
    vlines = cv2.dilate(cv2.erode(binary, kv), kv)
    kh = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(3, int(w * line_frac)), 1))
    hlines = cv2.dilate(cv2.erode(binary, kh), kh)
    cleaned = binary & (1 - vlines) & (1 - hlines)
    proj = cleaned.sum(axis=0).astype(np.float64)
    if return_rule_xs:
        return proj, vlines.any(axis=0)
    return proj


def fit_page_grid(projs: list[np.ndarray], n_chars: int,
                  full_widths: list[float] | None = None,
                  cell_step: float = 0.5, phase_step: int = 2,
                  cell_h_fixed: float | None = None
                  ) -> tuple[float, float]:
    """页级刚性网格拟合：在全部文字列的聚合投影上搜索 (相位, 格高)。

    刻本整版先划栏格再上字：**格高固定、跨列统一**；列首/列尾的空格
    占格位但无墨——因此网格必须锚定栏格证据（聚合投影的周期结构），
    而非单列的内容范围（抬头空格列按内容锚定会整体错位一格）。

    Args:
        cell_h_fixed: 给定时格高不再搜索（书级共识值），只搜相位。
            自由拟合的格高基准 `base=(bottom-top)/n_chars` 假设列是满的，
            稀疏页（目录、职名）与谐波锁定页会得到 1/2、1/3 的伪解，
            ±8% 的搜索窗永远跳不出去——格高只能由全书刚性先验给定。

    Returns:
        (phase, cell_h): 网格首线位置与固定格高。
    """
    page = np.sum(projs, axis=0)
    L = len(page)
    if page.sum() < 1:
        return 0.0, float(cell_h_fixed or L / n_chars)
    fw = float(sum(full_widths)) if full_widths else None
    top, bottom = content_range(page, min_run=0.25 * L / n_chars,
                                max_fill=0.9 * fw if fw else None)
    base = float(cell_h_fixed) if cell_h_fixed else (bottom - top) / n_chars
    smooth = _smooth(page, base)

    if cell_h_fixed:
        cell_hs = [float(cell_h_fixed)]
    else:
        cell_hs = list(np.arange(base * 0.92, base * 1.08, cell_step))

    best = (float(top), base)
    best_cost = float("inf")
    for cell_h in cell_hs:
        span = cell_h * n_chars
        # 相位范围：允许首格空/框偏差，网格可高于内容顶一格出头。
        # 格高固定时不再按 L-span 收窄上界——共识格高下整版可能略高于
        # 裁切后的页面（末格出界由 cells_from_bounds 裁掉）。
        p_lo = max(0.0, top - 1.2 * cell_h)
        p_hi = top + 1.2 * cell_h if cell_h_fixed \
            else min(top + 1.2 * cell_h, max(p_lo, L - span))
        for phase in np.arange(p_lo, p_hi + phase_step, phase_step):
            cost = _grid_cost(smooth, phase, cell_h, n_chars)
            if cost < best_cost:
                best_cost = cost
                best = (float(phase), float(cell_h))
    return best


def rigid_bounds(proj: np.ndarray, page_phase: float, cell_h: float,
                 n_chars: int, micro: float = 0.12,
                 phase_step: int = 1) -> list[float]:
    """单列刚性网格：格高固定，相位在页面相位 ±micro×格高 内微调。

    微调只容忍板歪/扫描形变；空列/稀疏列信号弱时代价面平坦，
    平局偏向页面相位（刻本栏格跨列统一）。"""
    L = len(proj)
    smooth = _smooth(proj, cell_h)
    r = micro * cell_h
    best_phase, best_cost = max(0.0, page_phase), float("inf")
    for phase in np.arange(max(0.0, page_phase - r),
                           page_phase + r + phase_step, phase_step):
        cost = _grid_cost(smooth, phase, cell_h, n_chars) \
            + 1e-3 * abs(phase - page_phase) / cell_h * max(1.0, smooth.mean())
        if cost < best_cost:
            best_cost, best_phase = cost, float(phase)
    return [best_phase + cell_h * k for k in range(n_chars + 1)]


def straddle_score(image: np.ndarray, result: dict) -> float:
    """骑线比：网格线上的墨 / 格中心的墨（逐列取中位）。

    这是切分质量的**直接**度量——字骑在格线上时线上墨接近格心墨
    （比值→1），对齐良好时线落字间空隙（比值→0.2±）。实测全书
    中位 0.38，骑线页 >0.8。"""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cell_h = result.get("grid", {}).get("cell_h") or 100.0
    ratios = []
    for col in result.get("columns", []):
        cells = [c for c in col.get("cells", []) if c.get("type") != "margin"]
        if not cells:
            continue
        x0 = int(col["left_x"]) + 2
        x1 = int(col["right_x"]) - 2
        if x1 - x0 < 8:
            continue
        crop = image[:, x0:x1]
        if crop.size == 0:
            continue
        sm = _smooth(column_projection(crop), cell_h)
        if sm.sum() < 1:
            continue
        L = len(sm)
        lines = [int(c["y_top"]) for c in cells] + [int(cells[-1]["y_bottom"])]
        centers = [int((c["y_top"] + c["y_bottom"]) / 2) for c in cells]
        lv = float(np.mean([sm[min(max(y, 0), L - 1)] for y in lines]))
        cv_ = float(np.mean([sm[min(max(y, 0), L - 1)] for y in centers]))
        if cv_ > 1:
            ratios.append(lv / cv_)
    return float(np.median(ratios)) if ratios else 0.0


def sweep_row_phase(image: np.ndarray, result: dict, cell_h: float,
                    n_steps: int = 32) -> tuple[float, float]:
    """全周期扫描行相位，返回 (最优首线全图 y, 该相位的骑线比)。

    直接优化骑线度量本身。相位**不能**跟随书级中位：实测相位相对
    版框全书并不一致（对齐良好页之间 σ≈0.45 格）——只能本页自扫。
    稀疏页（职名/目录）的谷-峰代价欠定正是原相位错拟的根源，
    骑线比对这类页仍然判别明确（字在格心 vs 骑线是硬事实）。"""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cols = []
    for col in result.get("columns", []):
        cells = [c for c in col.get("cells", []) if c.get("type") != "margin"]
        if not cells:
            continue
        x0, x1 = int(col["left_x"]) + 2, int(col["right_x"]) - 2
        if x1 - x0 < 8:
            continue
        crop = image[:, x0:x1]
        if crop.size == 0:
            continue
        sm = _smooth(column_projection(crop), cell_h)
        if sm.sum() >= 1:
            cols.append(sm)
    if not cols:
        return 0.0, float("inf")
    first = min(float(c["cells"][0]["y_top"]) if c.get("cells") else 0.0
                for c in result["columns"]
                if any(x.get("type") != "margin" for x in c.get("cells", [])))
    n = sum(1 for c in result["columns"][0].get("cells", [])
            if c.get("type") != "margin") or 21
    best_y, best_score = first, float("inf")
    for delta in np.linspace(-0.5, 0.5, n_steps, endpoint=False) * cell_h:
        y0 = first + delta
        ratios = []
        for sm in cols:
            L = len(sm)
            lines = np.clip(np.round(y0 + cell_h * np.arange(n + 1)).astype(int),
                            0, L - 1)
            centers = np.clip(
                np.round(y0 + cell_h * (np.arange(n) + 0.5)).astype(int),
                0, L - 1)
            cv_ = float(sm[centers].mean())
            if cv_ > 1:
                ratios.append(float(sm[lines].mean()) / cv_)
        score = float(np.median(ratios)) if ratios else float("inf")
        if score < best_score:
            best_score, best_y = score, float(y0)
    return best_y, best_score


def dp_boundaries(proj: np.ndarray, cell_h: float, n_chars: int,
                  phase_prior: float | None = None,
                  elastic: float = 0.15, step: int = 2,
                  beta: float = 1.0,
                  full_width: float | None = None) -> list[float]:
    """弹性网格动态规划：全局最优地选 n_chars+1 条网格线。

    写刻本手写上版，字距列内局部不均——刚性等距网格误差沿列累积。
    DP 保持"恰好 N 格"硬约束，允许每格高度在 ±elastic 内伸缩：

        cost = Σ smooth[线] − 0.5·Σ smooth[格中心]
             + β·mean(smooth)·Σ ((格高−cell_h)/(elastic·cell_h))²

    phase_prior 给定时（稀疏列，如职名页），首线锚定在先验相位附近，
    末线由 N×cell_h 推算——弱信号列跟随页面主流相位。
    """
    L = len(proj)
    smooth = _smooth(proj, cell_h)
    ys = np.arange(0, L, step)
    M = len(ys)
    line_cost = smooth[ys]
    d_lo = max(1, int((1.0 - elastic) * cell_h / step))
    d_hi = max(d_lo, int(np.ceil((1.0 + elastic) * cell_h / step)))
    pen_scale = beta * max(1.0, float(smooth.mean()))

    top, bottom = content_range(
        proj, min_run=0.25 * cell_h,
        max_fill=0.9 * full_width if full_width else None)
    if phase_prior is not None:
        s_lo, s_hi = phase_prior - 0.3 * cell_h, phase_prior + 0.3 * cell_h
        e_lo = phase_prior + n_chars * cell_h - 0.5 * cell_h
        e_hi = phase_prior + n_chars * cell_h + 0.5 * cell_h
    else:
        # 首末窗口各放宽到 2 格：content_range 只是粗定位（长游程可能
        # 混入边框/黑角），格中心峰项会驱动 DP 覆盖真实文字而非空白
        s_lo, s_hi = top - 0.5 * cell_h, top + 1.5 * cell_h
        e_lo, e_hi = bottom - 1.5 * cell_h, bottom + 0.5 * cell_h

    INF = 1e18
    dp = np.where((ys >= s_lo) & (ys <= s_hi), line_cost, INF)
    if phase_prior is not None:
        # 平局时偏向先验相位（零信号列锚定页面主流网格，而非窗口边缘）
        dp = dp + 1e-3 * pen_scale * np.abs(ys - phase_prior) / cell_h
    back = np.zeros((n_chars, M), dtype=np.int32)
    for k in range(n_chars):
        ndp = np.full(M, INF)
        nb = np.zeros(M, dtype=np.int32)
        for d in range(d_lo, d_hi + 1):
            if d >= M:
                break
            h = d * step
            pen = pen_scale * ((h - cell_h) / (elastic * cell_h)) ** 2
            mid = np.clip((ys[d:] - h // 2), 0, L - 1)
            cand = dp[:-d] + line_cost[d:] - 0.5 * smooth[mid] + pen
            better = cand < ndp[d:]
            ndp[d:][better] = cand[better]
            nb[d:][better] = np.arange(M - d)[better]
        dp, back[k] = ndp, nb

    end_mask = (ys >= e_lo) & (ys <= e_hi) & (dp < INF)
    dp_end = np.where(end_mask, dp, INF)
    if not np.isfinite(dp_end.min()) or dp_end.min() >= INF:
        dp_end = dp   # 末端约束不可满足时放开（严重残页兜底）
    j = int(np.argmin(dp_end))
    bounds = [float(ys[j])]
    for k in range(n_chars - 1, -1, -1):
        j = int(back[k][j])
        bounds.append(float(ys[j]))
    return list(reversed(bounds))


def refine_boundaries(proj: np.ndarray, offset: float, cell_h: float,
                      n_chars: int,
                      search_ratio: float = SEARCH_RATIO) -> list[float]:
    """逐线微调：每条内部网格线在 ±search_ratio×格高 内移到投影最低点。

    首尾线不动（列边界）；保持单调且相邻线距 ≥ 0.6×格高。
    """
    L = len(proj)
    kernel = max(3, int(cell_h * 0.08)) | 1
    smooth = np.convolve(proj, np.ones(kernel) / kernel, mode="same")

    lines = [min(max(offset + cell_h * k, 0.0), float(L))
             for k in range(n_chars + 1)]
    refined = [lines[0]]
    for k in range(1, n_chars):
        y = lines[k]
        r = cell_h * search_ratio
        lo = max(int(y - r), int(refined[-1] + 0.6 * cell_h), 0)
        hi = min(int(y + r), L - 1)
        if hi <= lo:
            refined.append(min(max(y, refined[-1] + 0.6 * cell_h), float(L)))
            continue
        window = smooth[lo:hi + 1]
        # 同值谷取离先验位置最近者
        min_v = window.min()
        cand = np.nonzero(window <= min_v + 1e-9)[0] + lo
        best = cand[np.argmin(np.abs(cand - y))]
        refined.append(float(best))
    refined.append(lines[-1])
    return refined


def _junk_free_ink(cell_gray: np.ndarray) -> float:
    """格内去「界行竖线段 + 贴边框横线」后的墨量占比（判空用）。

    界行竖线段与版框横线的墨量足以骗过朴素判空（0.05~0.15 ≫ 0.02），
    batch3 人工反馈 147 例 not_text 大多如此。剔除规则：
    - 竖直长线（≥0.55 格高）整体剔——字的竖笔不会纵贯半格以上还落单；
    - 水平长线（≥0.55 格宽）仅当**贴边**（组件 y 中心在格高 22% 以外
      边带）才剔——版框线贴格顶/格底，「一」的横笔在格中央。
    实测：真值垃圾 48% 直接判空，用户确认真字/截断半字 0 误杀。"""
    b = (cell_gray < BINARY_THRESHOLD).astype(np.uint8)
    h, w = b.shape
    if h < 6 or w < 6:
        return float(b.sum()) / max(1, b.size)
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(h * 0.55))))
    vl = cv2.dilate(cv2.erode(b, kv), kv)
    # 竖线还须**窄**（≤12% 格宽）：界行 4~8px / 格宽 110px ≈ 5%，
    # 字的竖笔虽长但更宽且带弯曲——不加宽度条件会误剔理想化直笔
    nv, labv, statsv, _ = cv2.connectedComponentsWithStats(vl, 8)
    vl_narrow = np.zeros_like(vl)
    for k in range(1, nv):
        if statsv[k][2] <= max(6, 0.12 * w):
            vl_narrow[labv == k] = 1
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(w * 0.55)), 1))
    hl = cv2.dilate(cv2.erode(b, kh), kh)
    n, lab, statsh, cent = cv2.connectedComponentsWithStats(hl, 8)
    hl_edge = np.zeros_like(hl)
    for k in range(1, n):
        cy = cent[k][1] / h
        if (cy < 0.22 or cy > 0.78) and statsh[k][3] <= max(6, 0.15 * h):
            hl_edge[lab == k] = 1
    clean = b & (1 - vl_narrow) & (1 - hl_edge)
    return float(clean.sum()) / b.size


def cells_from_bounds(col_gray: np.ndarray, bounds: list[float],
                      params: GridParams) -> list[dict]:
    """按给定网格线产出 cells（局部 y 坐标）。"""
    n_chars = len(bounds) - 1
    w = col_gray.shape[1]
    L = col_gray.shape[0]
    cells: list[dict] = []
    if bounds[0] > 0.5:
        cells.append({"type": "margin", "y_top": 0.0, "y_bottom": bounds[0]})
    for i in range(n_chars):
        y0, y1 = bounds[i], bounds[i + 1]
        ink = _junk_free_ink(col_gray[int(y0):int(y1)])
        if ink < params.empty_ink_ratio:
            cells.append({"type": "empty", "index": i,
                          "y_top": y0, "y_bottom": y1,
                          "text": None, "confidence": 0.0})
        else:
            cells.append({"type": "char", "index": i,
                          "y_top": y0, "y_bottom": y1,
                          "text": None, "confidence": 0.0})
    if bounds[-1] < L - 0.5:
        cells.append({"type": "margin", "y_top": bounds[-1],
                      "y_bottom": float(L)})
    return cells


SPREAD_PITCH = 1.4         # 列内组件中位间距超此倍格高 → 判定"拉开列"


def _merged_components(col_bin: np.ndarray, cell_h: float
                       ) -> list[tuple[float, float, float]]:
    """列内合并连通体：返回 [(y_center, y_min, y_max)]，按 y 升序。

    同字的多部件（上下结构、断笔）按间距 < 0.5 格合并；
    过滤噪点与贯穿线（高 > 1.6 格 = 界行）。"""
    n, _, stats, cent = cv2.connectedComponentsWithStats(col_bin, 8)
    parts = []
    for (x, y, w, h, area), (cx, cy) in zip(stats[1:], cent[1:]):
        if area < cell_h * 2.5 or h > 1.6 * cell_h or h < 6:
            continue
        parts.append((float(y), float(y + h)))
    parts.sort()
    merged: list[list[float]] = []
    for y0, y1 in parts:
        if merged and y0 - merged[-1][1] < 0.35 * cell_h:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])
    return [((a + b) / 2, a, b) for a, b in merged]


DENSE_SPLIT_MIN_H = 0.35    # 密排段切分：子字符最小高度（× 格高）
DENSE_SPLIT_VALLEY = 0.35   # 谷点判据：局部极小值 ≤ 段自身峰值的这个比例
OVERFLOW_CAP_RATIO = 3.0    # 单列格数硬上限（× n_chars），防噪声爆炸


def _split_dense_segment(col_gray: np.ndarray, a: float, b: float,
                         cell_h: float) -> list[tuple[float, float]]:
    """密排/压缩段内按墨迹谷点切分，不假定子字符等高。

    职名页标题过长时，刻工会把字压小塞进同一列高度——按标准格高猜
    这段有几个字必然低估（压缩后单字高度小于格高：实测一段 23 字的
    压缩标题按格高只猜出 15 字，导致整列因"格数超限"被打回刚性网格，
    23 字摊进 9 格，好几个字挤一格）。

    改用这段自己的行投影找局部墨量谷点：不管字被压缩到多小，真实字
    与字之间总有一处墨量低谷，谷点数 + 1 就是真实字数——不依赖任何
    绝对尺寸假设，一次性覆盖"拉开的人名段"（原逻辑已覆盖）和"压缩的
    超长标题段"（新增）。找不到清晰谷点（真·连笔）时按 0.95×格高
    均分兜底，不比原逻辑更差。
    """
    seg = col_gray[int(round(a)):int(round(b))]
    h = b - a
    proj = column_projection(seg)
    min_h = DENSE_SPLIT_MIN_H * cell_h

    def even_fallback() -> list[tuple[float, float]]:
        n_sub = max(1, int(round(h / (cell_h * 0.95))))
        step = h / n_sub
        return [(a + k * step, a + (k + 1) * step) for k in range(n_sub)]

    if proj.sum() < 1:
        return even_fallback()
    win = max(3, int(cell_h * 0.10)) | 1
    sm = np.convolve(proj, np.ones(win) / win, mode="same")
    peak = float(sm.max())
    if peak <= 0:
        return even_fallback()
    # 谷点：每一段"低于阈值"的连续区间取其最小值点，而不是逐点找局部
    # 极小值——后者对间距设下限会把压缩到比 min_h 还密的真实字距一并
    # 挡掉（实测把 11 字的压缩段只切出 6 段）；不设下限又会让平坦谷底
    # 上的每个像素都各算一个"局部极小"。按阈值分段取一个代表点两个
    # 问题一起解决，间距过近的伪谷交给下面的 merged_bounds 按 min_h 合并。
    below = sm < DENSE_SPLIT_VALLEY * peak
    valleys: list[int] = []
    i = 1
    while i < len(sm) - 1:
        if below[i]:
            j = i
            while j < len(sm) - 1 and below[j]:
                j += 1
            valleys.append(i + int(np.argmin(sm[i:j])))
            i = j
        else:
            i += 1
    bounds = [0.0] + [float(v) for v in valleys] + [float(len(sm))]
    merged_bounds = [bounds[0]]
    for x in bounds[1:]:
        if x - merged_bounds[-1] >= min_h:
            merged_bounds.append(x)
        else:
            merged_bounds[-1] = x          # 太窄的切段并回前一段
    if merged_bounds[-1] < bounds[-1]:
        merged_bounds[-1] = bounds[-1]
    if len(merged_bounds) < 3:             # 切不出像样的谷 → 均分兜底
        return even_fallback()
    return [(a + merged_bounds[i], a + merged_bounds[i + 1])
            for i in range(len(merged_bounds) - 1)]


def cells_from_components(col_gray: np.ndarray, cell_h: float, n_chars: int,
                          params: GridParams) -> list[dict] | None:
    """拉开列（职名/奉旨列名）的组件锚定混合切分。

    职名页排版有两种偏离刚性网格的方式，处理都基于同一套组件分析：
    - 官衔字**拉开**（字距 3.4~3.7 格，非整数倍，任何行相位都躲不开
      腰斩）——单字组件（高 ≤1.55 格）独立成格；
    - 标题过长时刻工把字**压缩**塞进同一列高度，格数因此**超过**
      n_chars——密排/压缩段组件（高 >1.55 格）按内部墨迹谷点切分
      （见 _split_dense_segment），而非假定子字符等于标准格高。

    idx 不再映射到 0..n_chars-1 的刚性网格位——超载列的字数本就超过
    n_chars，映射必然产生碰撞（实测把 23 字的列砸扁成 9 格）。组件
    已经是按 y 升序的真实阅读顺序，直接顺序编号即可，格数就是真实
    字数，不再向 n_chars 补齐空位。

    触发条件（证据不足返回 None 走刚性网格）：合并组件 ≥3、
    组件中心间距中至少 2 个 > 2.2 格、组件总数 ≤ 12、单个组件不超过
    8 格高。密排正文列组件会连成大段且间距小，绝不会误触发——这四条
    本身没变，变的只是"触发之后怎么切"。
    """
    col_bin = (col_gray < BINARY_THRESHOLD).astype(np.uint8)
    comps = _merged_components(col_bin, cell_h)
    if len(comps) < 3 or len(comps) > 12:
        return None
    # 碎屑（< 0.3 格高：版框残迹、贴边墨点）丢弃而非否决整列——
    # p108 职名列曾因列顶一条 0.09 格的框线残迹被一票否决。
    # 局限：拉开列里真正的"一"字也会被当碎屑丢掉（官衔中几乎不出现）。
    comps = [c for c in comps if (c[2] - c[1]) >= 0.3 * cell_h]
    if len(comps) < 3:
        return None
    centers = [c[0] for c in comps]
    gaps = np.diff(centers)
    if int((gaps > 2.2 * cell_h).sum()) < 2:
        return None
    heights = [(b - a) for _, a, b in comps]
    if not all(h <= 8.0 * cell_h for h in heights):
        return None
    L = col_gray.shape[0]
    pad = 0.10 * cell_h
    boxes: list[tuple[float, float]] = []      # 每格 (y0, y1)，已按 y 升序
    for cy, a, b in comps:
        h = b - a
        if h <= 1.55 * cell_h:                 # 单字组件
            boxes.append((max(0.0, a - pad), min(float(L), b + pad)))
        else:                                   # 密排/压缩段：谷点切分
            for sa, sb in _split_dense_segment(col_gray, a, b, cell_h):
                boxes.append((max(0.0, sa - pad * 0.5),
                              min(float(L), sb + pad * 0.5)))
    if len(boxes) > OVERFLOW_CAP_RATIO * n_chars:
        return None                            # 谷点也切不出数——噪声，放弃
    cells: list[dict] = []
    for idx, (y0, y1) in enumerate(boxes):
        kind = ("char" if _junk_free_ink(col_gray[int(y0):int(y1)])
                >= params.empty_ink_ratio else "empty")
        cells.append({"type": kind, "index": idx,
                      "y_top": y0, "y_bottom": y1,
                      "text": None, "confidence": 0.0})
    return cells


def segment_column(col_gray: np.ndarray, n_chars: int, params: GridParams,
                   shared_grid: tuple[float, float] | None = None) -> list[dict]:
    """单列切分 → cells（局部 y 坐标）。

    shared_grid=(offset, cell_h) 给定时从页面级共享网格出发做小范围微调
    （刻本整版同刻、跨列行对齐，稀疏列跟随全页网格不漂移）；
    缺省时独立拟合本列（单列场景/测试用）。
    """
    proj = column_projection(col_gray)
    L = len(proj)
    if shared_grid is not None:
        offset, cell_h = shared_grid
        bounds = dp_boundaries(proj, cell_h, n_chars, phase_prior=offset)
    elif proj.sum() < 1:   # 独立模式下的整列空白：均分
        cell = L / n_chars
        return [{"type": "empty", "index": i,
                 "y_top": i * cell, "y_bottom": (i + 1) * cell,
                 "text": None, "confidence": 0.0} for i in range(n_chars)]
    else:
        _, cell_h = fit_global_grid(proj, n_chars)
        bounds = dp_boundaries(proj, cell_h, n_chars)
    return cells_from_bounds(col_gray, bounds, params)


class GridSegmenter:
    """刻本网格切分器：phase2 layout + 页面图 → char_grid JSON。"""

    def __init__(self, chars_per_line: int, n_cols: int | None = None,
                 empty_ink_ratio: float = EMPTY_INK_RATIO,
                 search_ratio: float = SEARCH_RATIO):
        """n_cols 给定时启用列网格拟合（每半页列数，profile.lines_per_page），
        不再依赖 Phase 2 的列检测结果；None 时沿用 layout 的列。"""
        self.params = GridParams(chars_per_line, empty_ink_ratio, search_ratio)
        self.n_cols = n_cols

    # ── 纯函数核心 ────────────────────────────────────────

    def segment_page(self, image: np.ndarray, layout: dict,
                     grid_override: dict | None = None,
                     cell_h_prior: float | None = None,
                     row_phase_abs: float | None = None) -> dict:
        """grid_override 给定时跳过本页拟合，用书级共享网格参数
        （period/col_phase_rel/inset_l/inset_r/cell_h/row_phase_rel，
        相位以本页 inner_frame 为基准换算）——弱信号页专用。

        cell_h_prior 给定时只固定行格高（书级共识），相位仍按本页投影
        重搜——格高锁错（谐波/稀疏页）的页专用：这类页列网格正常，
        相位也是本页自身的，不该跟随书级中位。

        row_phase_abs 给定时行相位钉死为该值（全图 y 坐标的网格首线），
        供骑线重扫（Pass 2c）择优后回填——注意**不能**跟随书级中位相位：
        实测相位相对版框全书并不一致（版框检测基准页间漂移），
        对齐良好的页之间相位标准差高达 0.45 格。"""
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = image.shape[:2]
        n = self.params.chars_per_line

        borders = layout.get("borders", {})
        inner = borders.get("inner_frame", {})
        col_top = inner.get("top", {}).get("intercept", 0)
        col_bottom = inner.get("bottom", {}).get("intercept", h)
        frame_left = inner.get("left", {}).get("intercept", 0)

        grid_meta: dict = {}
        if self.n_cols:
            # 列网格拟合：列宽/列距与行网格同为刻本刚性先验，
            # 页级拟合一个 (相位, 列距)，替代 Phase 2 的自由列检测
            # （自由检测会劈裂/粘连列，切残的字残形趋同致跨字污染）。
            vproj, rule_xs = page_column_projection(image,
                                                    return_rule_xs=True)
            page_ink = float(vproj.sum())
            if grid_override:
                # 书级共享网格（刻本整书同版式）：弱信号页（空白余纸、
                # 稀疏职名页）自身拟合不可靠，跟随书级中位参数，
                # 相位以本页边框为基准换算。
                period = grid_override["period"]
                cx0 = frame_left + grid_override["col_phase_rel"]
                inset_l = grid_override["inset_l"]
                inset_r = grid_override["inset_r"]
            else:
                cx0, period = fit_page_grid([vproj], self.n_cols,
                                            full_widths=[image.shape[0]])
                # 列格 = 文字带 + 界行缝（完整周期）。文字带在周期内的
                # 位置同样刚性固定：逐列格测文字带左右内缩，取页面中位
                # 统一应用——否则图块裹进界行，竖线隔离会误伤大半字符。
                insets: list[tuple[float, float]] = []
                for k in range(self.n_cols):
                    s, e = int(cx0 + period * k), int(cx0 + period * (k + 1))
                    seg = vproj[max(0, s):min(len(vproj), e)]
                    if len(seg) < 4 or seg.sum() < 1:
                        continue
                    t, b = content_range(seg, min_run=0.1 * period)
                    if b - t >= 0.4 * period:      # 空列/噪声段不计入
                        insets.append((float(t), float(len(seg) - b)))
                if insets:
                    inset_l = float(np.median([a for a, _ in insets]))
                    inset_r = float(np.median([b for _, b in insets]))
                else:
                    inset_l = inset_r = period * 0.08
            columns_info = [
                {"index": self.n_cols - k,     # 从右到左编号，最右列=1
                 "left_x": cx0 + period * k + inset_l,
                 "right_x": cx0 + period * (k + 1) - inset_r}
                for k in range(self.n_cols)]
            # 列拟合质量：界行竖线落入列格内部的比例。拟合正确时
            # 界行全在列格之间的缝里；错位半周期则大量进入列内——
            # 这正是下游"图块裹线被隔离"的直接前因。
            in_col = total_rule = 0
            for c in columns_info:
                lo, hi = int(c["left_x"]) + 3, int(c["right_x"]) - 3
                if hi > lo:
                    in_col += int(rule_xs[lo:hi].sum())
            total_rule = max(1, int(rule_xs.sum()))
            grid_meta = {"page_ink": page_ink, "period": float(period),
                         "col_phase_rel": float(cx0 - frame_left),
                         "inset_l": float(inset_l),
                         "inset_r": float(inset_r),
                         "rule_in_col": round(in_col / total_rule, 4)}
        else:
            columns_info = layout.get("columns", {}).get("columns", []) \
                or borders.get("columns", [])

        # 刻本文字列宽度一致：过滤版心/界行缝等窄列
        widths = [c["right_x"] - c["left_x"] for c in columns_info]
        median_w = float(np.median(widths)) if widths else 0.0

        # 纵向外扩一格：inner_frame 检测偏差可接近一个字高，外扩不足会
        # 裁掉首/末字；网格真实范围由投影内容决定（content_range 会剔除
        # 外扩带进来的边框线短游程）。
        pad = int((col_bottom - col_top) / n) if col_bottom > col_top else 0
        y1 = max(0, int(col_top) - pad)
        y2 = min(h, int(col_bottom) + pad)

        # 第一遍：收集文字列裁切与投影
        text_cols: list[tuple[dict, np.ndarray, np.ndarray]] = []
        result_columns = []
        for col in columns_info:
            left_x, right_x = float(col["left_x"]), float(col["right_x"])
            col_w = right_x - left_x
            col_result = {"index": col["index"], "left_x": left_x,
                          "right_x": right_x, "ocr_text": "", "cells": []}
            result_columns.append(col_result)
            x1 = max(0, int(left_x) + 2)
            x2 = min(w, int(right_x) - 2)
            if col_w < median_w * MIN_COL_WIDTH_RATIO or x2 <= x1 or y2 <= y1:
                col_result["skipped"] = "non_text_column"
                continue
            crop = image[y1:y2, x1:x2]
            text_cols.append((col_result, crop, column_projection(crop)))

        # 刚性网格模型：刻本整版先划栏格再上字，**格高固定、跨列统一**；
        # 列首/列尾空格占格位但无墨（判空处理），网格锚定栏格周期证据
        # （页级聚合投影），绝不按单列内容范围锚定——抬头空格列会错一格。
        # 每列仅允许相位 ±0.12 格微调（板歪/扫描形变），格高不变。
        if text_cols:
            if row_phase_abs is not None:
                cell_h = cell_h_prior or (col_bottom - col_top) / n
                page_phase = float(row_phase_abs) - y1
            elif grid_override:
                cell_h = grid_override["cell_h"]
                # row_phase_rel 以 frame_top 为基准 → 换算到 crop 坐标
                page_phase = float(col_top) + grid_override["row_phase_rel"] - y1
            else:
                page_phase, cell_h = fit_page_grid(
                    [p for _, _, p in text_cols], n,
                    full_widths=[crop.shape[1] for _, crop, _ in text_cols],
                    cell_h_fixed=cell_h_prior)
            grid_meta.update({"cell_h": float(cell_h),
                              "row_phase_rel": float(y1 + page_phase - col_top)})
            for col_result, crop, proj in text_cols:
                # 拉开列（职名页官衔，字距 ~3.5 格非整数倍）优先组件锚定
                cells = cells_from_components(crop, cell_h, n, self.params)
                if cells is None:
                    bounds = rigid_bounds(proj, page_phase, cell_h, n)
                    cells = cells_from_bounds(crop, bounds, self.params)
                else:
                    col_result["spread_col"] = True
                for c in cells:   # 局部 → 全图坐标
                    c["y_top"] += y1
                    c["y_bottom"] += y1
                col_result["cells"] = cells

        return {
            "image_size": {"width": w, "height": h},
            "chars_per_line": n,
            "segmenter": "grid_strict",
            "grid": grid_meta,
            "columns": result_columns,
        }

    # ── IO 壳 ────────────────────────────────────────────

    def run_book(self, book_out_dir: Path,
                 source_dir: Path | None = None,
                 name_filter: set[str] | None = None) -> dict:
        """遍历 phase2_layout/*_layout.json → 写 phase3_char_grid/。"""
        book_out_dir = Path(book_out_dir)
        layout_dir = book_out_dir / "phase2_layout"
        layout_files = sorted(layout_dir.glob("*_layout.json"))
        if name_filter is not None:
            layout_files = [f for f in layout_files
                            if f.stem.replace("_layout", "") in name_filter]
        if not layout_files:
            raise FileNotFoundError(f"未找到 layout JSON: {layout_dir}"
                                    "（请先运行 extract --steps layout）")

        src = Path(source_dir) if source_dir \
            else CharExtractor._resolve_source_dir(book_out_dir)
        out_dir = book_out_dir / "phase3_char_grid"
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Pass 1: 逐页独立拟合，收集网格参数与墨量 ──
        results: dict[str, dict] = {}
        pages: list[tuple[str, Path, dict]] = []
        for lf in layout_files:
            stem = lf.stem.replace("_layout", "")
            img_path = CharExtractor._find_page_image(src, stem)
            if img_path is None:
                print(f"  跳过 {stem}: 找不到页面图")
                continue
            image = imread(str(img_path))
            if image is None:
                continue
            with open(lf, encoding="utf-8") as f:
                layout = json.load(f)
            pages.append((stem, img_path, layout))   # 不缓存像素，弱页重读
            results[stem] = self.segment_page(image, layout)

        # ── Pass 2a: 书级格高共识，校正格高锁错的页 ──
        # 刻本全书同版：格高是**物理刚性常量**，一页不可能是别页的 1/2。
        # 自由拟合的基准 base=(bottom-top)/n_chars 假设列满，稀疏页
        # （目录/职名）与密排页的谐波锁定都会落到 1/2、1/3 的伪解上，
        # ±8% 搜索窗跳不出来。这类页列网格与墨量都正常，现有"弱页"
        # 判据（低墨量 / rule_in_col 高）完全抓不到——必须用格高本身判。
        n_row_fix = 0
        cell_hs = [r["grid"]["cell_h"] for r in results.values()
                   if r.get("grid", {}).get("cell_h")]
        if len(cell_hs) >= 5:
            consensus_h = float(np.median(cell_hs))
            off_grid = [s for s, r in results.items()
                        if r.get("grid", {}).get("cell_h")
                        and abs(r["grid"]["cell_h"] - consensus_h)
                        > CELL_H_TOL * consensus_h]
            for stem, img_path, layout in pages:
                if stem not in off_grid:
                    continue
                image = imread(str(img_path))
                if image is None:
                    continue
                # 格高偏离共识本身即失败证据（物理上不可能），无需择优
                # 门控——rule_in_col 度量的是列相位，对行格高无判别力，
                # 且这些页它已经是 0，任何门控都会一律拒绝校正。
                results[stem] = self.segment_page(
                    image, layout, cell_h_prior=consensus_h)
                n_row_fix += 1
            if n_row_fix:
                print(f"  书级格高共识 {consensus_h:.1f}px，"
                      f"校正格高锁错页 {n_row_fix} 张")

        # ── Pass 2b: 行相位骑线重扫 ──
        # 直接质量信号：骑线比（straddle_score）。稀疏页（职名/目录）
        # 谷-峰代价欠定导致相位错拟半格，字被上下腰斩——batch2 人工
        # 反馈 31 例 truncated 全部源于此。相位不能跟随书级中位
        # （相对版框不一致，见 sweep_row_phase 注），本页全周期自扫，
        # 骑线比至少改善 STRADDLE_GAIN 才接受。
        n_phase_fix = 0
        if cell_hs and len(cell_hs) >= 5:
            for stem, img_path, layout in pages:
                res = results[stem]
                if not res.get("grid", {}).get("cell_h"):
                    continue
                image = imread(str(img_path))
                if image is None:
                    continue
                cur = straddle_score(image, res)
                if cur <= STRADDLE_OK:
                    continue
                y_best, sc_best = sweep_row_phase(image, res, consensus_h)
                if sc_best < cur - STRADDLE_GAIN:
                    redone = self.segment_page(image, layout,
                                               cell_h_prior=consensus_h,
                                               row_phase_abs=y_best)
                    if straddle_score(image, redone) < cur - STRADDLE_GAIN:
                        results[stem] = redone
                        n_phase_fix += 1
            if n_phase_fix:
                print(f"  行相位骑线重扫修正 {n_phase_fix} 张")

        # ── Pass 2c: 书级共享网格校正弱信号页 ──
        # 刻本整书同版式：列距/字高/相位（相对边框）全书一致。
        # 空白余纸页、稀疏职名页自身拟合不可靠（相位骑到界行/乱套），
        # 用**强信号页的中位参数**重建其网格。
        n_weak = 0
        if self.n_cols and len(pages) >= 5:
            inks = {s: r["grid"].get("page_ink", 0.0)
                    for s, r in results.items() if r.get("grid")}
            median_ink = float(np.median(list(inks.values()))) if inks else 0.0
            strong = [s for s, v in inks.items() if v >= 0.5 * median_ink]
            if strong and median_ink > 0:
                keys = ("period", "col_phase_rel", "inset_l",
                        "inset_r", "cell_h", "row_phase_rel")
                override = {
                    key: float(np.median(
                        [results[s]["grid"][key] for s in strong
                         if key in results[s]["grid"]]))
                    for key in keys}

                # 失败判据（直接质量信号，不用参数偏离——相位的边框基准
                # 页间天然抖动，偏离判据会把好页错判失败并套上不准的中位）:
                # 1) 墨量过低: 空白余纸页, 纯界行上拟合乱套;
                # 2) rule_in_col 高: 界行竖线大量落入列格内部 = 列相位错.
                weak = {s for s, v in inks.items()
                        if v < 0.3 * median_ink
                        or results[s]["grid"].get("rule_in_col", 0) > 0.2}
                for stem, img_path, layout in pages:
                    if stem in weak:
                        image = imread(str(img_path))
                        if image is None:
                            continue
                        redone = self.segment_page(
                            image, layout, grid_override=override)
                        # 择优：校正绝不允许把页面改差（书级相位的边框
                        # 基准对个别页也可能不准）
                        old_q = results[stem]["grid"].get("rule_in_col", 1.0)
                        new_q = redone["grid"].get("rule_in_col", 1.0)
                        # rule_in_col 只度量列相位；行相位跟随书级中位曾把
                        # 多页字腰斩（相对版框不一致）——骑线比不得恶化
                        if new_q <= old_q and (
                                straddle_score(image, redone)
                                <= straddle_score(image, results[stem]) + 0.05):
                            results[stem] = redone
                            n_weak += 1
                if n_weak:
                    print(f"  书级网格校正弱信号页 {n_weak} 张")

        n_pages = n_chars = n_empty = 0
        for stem, _, _ in pages:
            result = results[stem]
            with open(out_dir / f"{stem}_char_grid.json", "w",
                      encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            pc = sum(1 for c in result["columns"] for x in c["cells"]
                     if x["type"] == "char")
            pe = sum(1 for c in result["columns"] for x in c["cells"]
                     if x["type"] == "empty")
            n_chars += pc
            n_empty += pe
            n_pages += 1

        meta = {"segmenter": "grid_strict",
                "params": {"chars_per_line": self.params.chars_per_line,
                           "empty_ink_ratio": self.params.empty_ink_ratio,
                           "search_ratio": self.params.search_ratio},
                "stats": {"pages": n_pages, "chars": n_chars,
                          "empty": n_empty, "weak_pages": n_weak,
                          "row_fixed_pages": n_row_fix,
                          "phase_fixed_pages": n_phase_fix}}
        with open(out_dir / "grid_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta
