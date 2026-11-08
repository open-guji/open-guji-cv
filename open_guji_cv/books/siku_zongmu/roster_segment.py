"""职名页（roster）单列切分：不定字数，按墨迹二维结构递归切（overview#450，S4）。

为什么不走 `row_boundaries.segment_column`
------------------------------------------
刻本正文每列刻满 `chars_per_line` 格，固定格数的弹性 DP 是对的先验。职名页
（四庫總目卷首 vol01 p89–132「勘閱繕校諸臣職名」）不是：一列 =「官衔段 + 偏右
小字『臣』+ 人名段」，官衔 1～20 字不等——字少时**匀开撑满**（字距 2～4 格，非
整数），字多时**大字密排**甚至压扁到半格高，还有**雙行小字**；人名 1～3 字贴底。
按 21 格硬切要么 DP 无解（L0u「版式未支持」），要么更糟——**切出来、过闸、字数
错**（dataset column-layout 12 页职名样本上 main 只有 21/97 列字数对）。

算法（只看本列墨迹，不假定格数）
--------------------------------
1. 去噪：斑点、界行残段（长细竖条/斜条）、上下框横条残留。
2. 横向投影切成**墨带**（行间空白 > 2px 即断）。
3. **压扁密排段**：相邻带间隙 < 0.35em、≥4 带、带高相近（CV<0.35）且扁
   （高/宽 0.35–0.7）——这些带各是一个压扁的字，**不许再并**；段内过高的带
   （两字粘连）按段字距切。
4. 其余带**并碎块**：上下两块并后高 ≤ 1.2×max(宽, 0.5em) 且间隙 < 0.35em
   （思、吉、文 这类上下分离的字）。
5. 比一字高（> 1.25em）的带找**左右分栏**：中线 30–70% 内墨最少的竖缝墨量
   ≤ 4% 带高，就把**连通体按质心**分到左右（不按像素硬切——双行两行相位不齐，
   笔画会越过中线）。雙行读序右行→左行（`jiazhu_a` / `jiazhu_b`）；
   一侧只有一个字（官衔末字旁的「臣」）→ 按 y 排读序；两侧都 ≥2 字 → 雙行（字号不一定小）。
6. 仍过高（> 1.45×max(宽, 0.85em)）的带 = 粘连密排：投影谷点 DP 切，字数在候选里
   挑（≥3em 的段用投影自相关估字距，短段用「字近方形」先验）。**这一类字数是推
   出来的不是看出来的**，列级标 `dense_guess` 交人核。
7. 最后丢掉 < 0.3em 的碎屑。

写本（史記文淵閣本职名页，2026-10-29）多两处不同，各加一步：
- 「臣」不自占一行，斜贴在官衔末字右下、人名首字右上，和邻字粘成一带：先照上面切一遍，
  从自成一带的「臣」量出全页臣行（`_chen_row`），第二遍在臣行附近把粘着的偏右小字按连通体拆出
  （`_split_side_small`）。只在臣行附近认，雙行小注的右行、「部」的「阝」不会被当成「臣」。
- 版框线粗细不匀、断续，整行横跨认不全：列端扁块当框线残段丢掉（`_drop_edge_bars`）。
密排列字压扁到彼此相粘（几何上没有缝），这一型仍数不准，要字数先验或识别参与切分。

殿本 vol01 换 Commons 新图后（2026-11-08，A34 交 001-r6 切坏格）多两处，一律生效（不是开关）：
- 大字雙行两行相位错开，高带之间夹的「左右各一字」矮带被当一个字（p87 c9「士武」「文英」）：
  相邻、分得出左右的带连成一段整段分栏（`_lr_runs`），分栏后按两侧墨心修正贴缝偏旁归边（p87 c7「部」的「阝」）。
- 新图「臣」0.83em，比偏右小字上限 0.8em 大，和上字并成一格（p99 c2「修臣」）：上限放到 0.9em。
雙行一侧里的压扁粘连字（p88 c6「內務」、c1「筵日」）几何仍数不准，`_glyph_refine` 不碰雙行列。

字号 em 取**全页**孤立大字（宽 > 0.45 列宽、高宽比 0.6–1.25）高的中位数——单列估在
雙行列上会偏小。

量与已知局限（2026-10-07，vol01 真原图 p89–132，逐列字数对 12 页 106 列目测小金标）
-----------------------------------------------------------------------------------
- 106 列里 101 列字数全对（main 固定 21 格：非空格计数只对 30/90，而 44 页**全部过闸**）；
- 错的 5 列全在 p90（大字压扁粘连 + 雙行），都带 `roster_dense_guess` / `roster_jiazhu`，
  全卷 44 页 396 列共 24 列（6%）带这两个标，交人核；
- 雙行另有一型「相位对齐」（p89：每条横带左右各一字），靠「连续 ≥3 条带都能分成两侧方字」
  认；个别行（一侧空、或一侧是窄偏旁字）认不出，会当一字——这类列也都带 `roster_jiazhu`；
- 粘连压扁字投影上没有可靠周期（p90 自相关峰仅 0.15），靠几何分不清「两个压扁字」与
  「一个上下结构字」——负结果，下一步要靠识别参与切分。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi

# ── 常量（均以 em = 全页大字字身高 为单位，除非注明）───────────────────
BAND_GAP_PX = 2            # 行间空白 ≤ 此像素不断带
RUN_GAP = 0.35             # 同一密排段内相邻带间隙上限
FRAG_MAX_ASPECT = 1.2      # 碎块并字：并后高 ≤ 此 × max(宽, 0.5em)
LR_MIN_H = 1.25            # 带高 > 此 × em 才试左右分栏
LR_GAP_INK = 0.04          # 分栏缝墨量 ≤ 此 × 带高
LR_SIDE_MIN = 0.15         # 分栏后每侧墨量至少占带墨量的比例
LR_WIDE = 0.55             # 雙行段的强带：分栏后两侧都至少这么宽（× em），左右结构单字的半边没这么宽（_lr_runs）
LR_FLAT = 0.6              # 高 < 此 × 宽算扁块（_flat_count）
LR_FLAT_EXTRA = 2          # 整段分栏的扁块数比逐带处理最多多这么多（_lr_items）
LEAD_MAX_W = 0.6           # 雙行段开头右行单字：宽 ≤ 此 × 列宽（_lead_in_jiazhu）
LR_REFINE_ITER = 3         # 分栏后按两侧墨心重新归边的轮数（_split_lr）
DENSE_H = 1.45             # 带高 > 此 × max(宽, 0.85em) 算粘连密排
PAIR_RUN = 3               # 相位对齐雙行：至少连续这么多条「左右两方字」带
PAIR_MAX_ASPECT = 1.6      # 两侧各自高/宽 ≤ 此（窄偏旁高宽比常 >1.8）
SPECK = 0.3                # 字框长边 < 此 × em 当碎屑丢
ISOLATED_SMALL = 0.45      # 长边 < 此 × em、且上或下离邻字 ≥ ISOLATED_GAP × em 的孤立小块当墨点丢
ISOLATED_GAP = 0.5         # （「臣」也小，但上贴官衔末字、下贴人名，两侧都近）
EDGE_ZONE = 0.05           # 列图上下这个比例内的扁块当框线残段（_drop_edge_bars）
EDGE_BAR_H = 0.15          # 框线残段高上限（× em）
SIDE_MIN_H = 1.1           # 带高 > 此 × em 才试拆偏右小字（写本「臣」斜贴邻字，见 _split_side_small）
SIDE_MAX = 0.9             # 偏右小字并框长边上限（× em）（殿本 vol01 新图「臣」0.83em，原 0.8 拆不出）
SIDE_OVERLAP = 0.5         # 偏右小字与邻字 y 重叠上限（× 小字高）
CHEN_TOL = 1.0             # 偏右小字上缘离全页「臣」行的上限（× em）
SIDE_MIN = 0.3             # 偏右小字并框短边下限（× em）：再小是字里的点画（「戈」右上点），不是字


@dataclass
class RosterItem:
    """一个字（列图坐标，左上原点）。kind: char | jiazhu_a | jiazhu_b。"""
    y0: int
    x0: int
    y1: int
    x1: int
    kind: str = "char"
    dense_guess: bool = False
    glyph: str | None = None        # 字形库精修切出的片：库里最像的字（只作诊断，不当识别结果）


@dataclass
class RosterColumn:
    items: list[RosterItem] = field(default_factory=list)
    em: float = 0.0
    flags: list[str] = field(default_factory=list)


# ── 基本量 ───────────────────────────────────────────────────────────────
def _xext(m: np.ndarray, y0: int | None = None, y1: int | None = None) -> tuple[int, int]:
    sub = m if y0 is None else m[y0:y1]
    xs = np.flatnonzero(sub.any(0))
    return (int(xs[0]), int(xs[-1]) + 1) if len(xs) else (0, 0)


def _bands(m: np.ndarray, gap: int = BAND_GAP_PX) -> list[list[int]]:
    p = m.any(1)
    out: list[list[int]] = []
    y, h = 0, len(p)
    while y < h:
        if p[y]:
            y0 = y
            while y < h and p[y]:
                y += 1
            if out and y0 - out[-1][1] <= gap:
                out[-1][1] = y
            else:
                out.append([y0, y])
        else:
            y += 1
    return out


def _tight(m: np.ndarray, y0: int, y1: int) -> list[int] | None:
    ys, xs = np.nonzero(m[y0:y1])
    if len(ys) == 0:
        return None
    return [y0 + int(ys.min()), int(xs.min()), y0 + int(ys.max()) + 1, int(xs.max()) + 1]


# ── 去噪 ────────────────────────────────────────────────────────────────
def _clear_edge_bars(ink: np.ndarray, width: float) -> np.ndarray:
    """列图上下 4% 内、墨横跨 >0.8 列宽的行（版框横条残留）清掉。"""
    h = ink.shape[0]
    e = int(0.04 * h)
    for y in list(range(e)) + list(range(h - e, h)):
        xs = np.flatnonzero(ink[y])
        if len(xs) and xs[-1] - xs[0] > 0.8 * width and ink[y].sum() > 0.6 * width:
            ink[y] = False
    return ink


def _denoise(ink: np.ndarray, width: float) -> np.ndarray:
    h_img = ink.shape[0]
    lab, n = ndi.label(ink, structure=np.ones((3, 3)))
    if n == 0:
        return ink
    area = ndi.sum(ink, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    for i, o in enumerate(ndi.find_objects(lab), 1):
        h = o[0].stop - o[0].start
        w = o[1].stop - o[1].start
        a = area[i - 1]
        if a < max(12.0, 0.0015 * width * width):
            continue                                       # 斑点
        if h > 0.6 * h_img and w < 0.08 * width:
            continue                                       # 界行残段
        if h > 0.2 * h_img and a / h < 0.06 * width:
            continue                                       # 斜界行残段：长而细
        if w > 0.4 * width and h < 0.15 * width and (o[0].start < 0.05 * h_img
                                                      or o[0].stop > 0.95 * h_img):
            continue                                       # 上下框残段
        keep[i] = True
    return keep[lab]


def prepare(gray: np.ndarray, content_x: tuple[float, float] | None,
            ink_threshold: int = 128) -> tuple[np.ndarray, float]:
    """列图 → (去噪后的墨 mask，内容宽)。content_x 之外的墨不要。"""
    ink = gray < ink_threshold
    if content_x is not None:
        a, b = int(content_x[0]), int(content_x[1])
        m = np.zeros_like(ink)
        m[:, a:b] = ink[:, a:b]
        ink, width = m, float(b - a)
    else:
        width = float(ink.shape[1])
    return _denoise(_clear_edge_bars(ink, width), width), width


def page_em(cols: list[tuple[np.ndarray, float]]) -> float | None:
    """全页孤立大字字身高的中位数；样本 < 3 返回 None。"""
    hs: list[int] = []
    for ink, width in cols:
        for y0, y1 in _bands(ink):
            x0, x1 = _xext(ink, y0, y1)
            w, h = x1 - x0, y1 - y0
            if w > 0.45 * width and 0.6 * w < h < 1.25 * w:
                hs.append(max(h, w))
    return float(np.median(hs)) if len(hs) >= 3 else None


# ── 带的分组与合并 ───────────────────────────────────────────────────────
def _compressed_runs(m: np.ndarray, bs: list[list[int]], em: float) -> dict[int, float]:
    """压扁密排段里的带 → 段字距。不在段里的带不出现在返回值里。"""
    pitch: dict[int, float] = {}
    i = 0
    while i < len(bs):
        j = i
        while j + 1 < len(bs) and bs[j + 1][0] - bs[j][1] < RUN_GAP * em:
            j += 1
        if j - i + 1 >= 3:
            hs, ok = [], []
            for k in range(i, j + 1):
                x0, x1 = _xext(m, bs[k][0], bs[k][1])
                w = max(1, x1 - x0)
                h = bs[k][1] - bs[k][0]
                hs.append(h)
                ok.append(0.35 <= h / w <= 0.7 and w > 0.5 * em)
            sel = np.array(hs, float)[np.array(ok)]
            if len(sel) >= 4 and sel.std() / sel.mean() < 0.35:
                p = float(np.median(sel))
                for k in range(i, j + 1):
                    if bs[k][1] - bs[k][0] >= 0.75 * p:
                        pitch[k] = p
        i = j + 1
    return pitch


def _is_side(box: tuple[int, int, int, int], em: float, col_x: tuple[int, int]) -> bool:
    """(y0, x0, y1, x1) 是不是偏右小字：整个在列中线右边、大小像个小字。"""
    h, w = box[2] - box[0], box[3] - box[1]
    mid = (col_x[0] + col_x[1]) / 2
    return (SIDE_MIN * em <= min(h, w) and max(h, w) <= SIDE_MAX * em
            and box[1] >= mid - 0.1 * em and (box[1] + box[3]) / 2 > mid)


def _merge_frags(m: np.ndarray, bs: list[list[int]], em: float) -> list[list[int]]:
    """碎块并字，每次并间隙最小的一对，直到没有可并的。"""
    bs = [list(b) for b in bs]
    while len(bs) > 1:
        best = None
        for i in range(len(bs) - 1):
            a, b = bs[i], bs[i + 1]
            gap = b[0] - a[1]
            x0, x1 = _xext(m, a[0], b[1])
            if gap < RUN_GAP * em and b[1] - a[0] <= FRAG_MAX_ASPECT * max(x1 - x0, 0.5 * em):
                if best is None or gap < best[0]:
                    best = (gap, i)
        if best is None:
            break
        i = best[1]
        bs[i] = [bs[i][0], bs[i + 1][1]]
        del bs[i + 1]
    return bs


def _split_lr(band: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """一条带找左右分栏：中线附近墨最少的竖缝够干净，就按连通体质心分两侧。"""
    x0, x1 = _xext(band)
    w, h = x1 - x0, band.shape[0]
    if w <= 0:
        return None
    prof = band.sum(0)
    lo, hi = x0 + int(0.3 * w), x0 + int(0.7 * w)
    if hi <= lo:
        return None
    xs = lo + int(np.argmin(prof[lo:hi]))
    if prof[xs] > LR_GAP_INK * h:
        return None
    lab, n = ndi.label(band, structure=np.ones((3, 3)))
    if n < 2:
        return None
    idx = range(1, n + 1)
    cx = np.array([c for _, c in ndi.center_of_mass(band, lab, idx)])
    mass = np.asarray(ndi.sum(band, lab, idx), float)
    is_r = cx >= xs
    # 两侧墨心修正（2-means）：竖缝取的是墨最少的一列，雙行两行相位错开时它可能落在一侧某字里头
    # （「部」的「咅」与「阝」之间），贴缝的偏旁按质心归错边；改按离哪侧墨心近归边，迭代到不变
    for _ in range(LR_REFINE_ITER):
        if is_r.all() or not is_r.any():
            break
        mr = np.average(cx[is_r], weights=mass[is_r])
        ml = np.average(cx[~is_r], weights=mass[~is_r])
        new = np.abs(cx - mr) < np.abs(cx - ml)
        if (new == is_r).all():
            break
        is_r = new
    right, left = np.isin(lab, np.flatnonzero(is_r) + 1), np.isin(lab, np.flatnonzero(~is_r) + 1)
    tot = band.sum()
    if right.sum() < LR_SIDE_MIN * tot or left.sum() < LR_SIDE_MIN * tot:
        return None
    return right, left


def _split_side_small(band: np.ndarray, em: float, col_x: tuple[int, int],
                      chen: float) -> list[np.ndarray] | None:
    """一条带里有偏右小字粘着上下邻字（写本的「臣」斜贴在官衔末字右下、人名首字右上）。

    连通体按质心 y 排开，取连续的一组当小字：并框是偏右小字（`_is_side`）、上缘在全页「臣」行
    （`chen`，带内坐标）±CHEN_TOL×em 内，且大半露在上下两侧的字外、露出的几行左边没有墨，就按连通体
    把带分成 上｜小字｜下 几段（自上而下返回；上下段可以还有几个字，回 `_seg_mask` 接着切）。刻本的「臣」自占一行，带本来就断开，走不到这里。"""
    lab, n = ndi.label(band, structure=np.ones((3, 3)))
    if n < 2:
        return None
    objs = ndi.find_objects(lab)
    order = sorted(range(n), key=lambda i: (objs[i][0].start + objs[i][0].stop) / 2)

    def box(ids):
        return (min(objs[i][0].start for i in ids), min(objs[i][1].start for i in ids),
                max(objs[i][0].stop for i in ids), max(objs[i][1].stop for i in ids))

    def clear(side, ids):
        # 小字只斜贴着邻字、大半露在它上下；整个落在邻字高度里的是字的右半边（「桐」的「同」）
        if not ids:
            return True
        b = box(ids)
        return min(side[2], b[2]) - max(side[0], b[0]) <= SIDE_OVERLAP * (side[2] - side[0])

    for k1 in range(n):
        for k2 in range(k1 + 1, n + 1):
            if k2 - k1 == n:
                continue
            up, mid, dn = order[:k1], order[k1:k2], order[k2:]
            side = box(mid)
            if not (_is_side(side, em, col_x) and abs(side[0] - chen) <= CHEN_TOL * em
                    and clear(side, up) and clear(side, dn)):
                continue
            # 露出来的那几行，小字左边得是空的：雙行小注的右行、「部」的「阝」左边都有字
            rows = np.ones(side[2] - side[0], bool)
            for ids in (up, dn):
                if ids:
                    b = box(ids)
                    rows[max(0, b[0] - side[0]):max(0, b[2] - side[0])] = False
            if band[side[0]:side[2]][rows, :side[1]].sum() <= 0.02 * rows.sum() * (side[3] - side[1]):
                parts = []
                for ids in (up, mid, dn):
                    if ids:
                        part = np.zeros_like(band)
                        for i in ids:
                            part[lab == i + 1] = True
                        parts.append(part)
                return parts
    return None


def _pair_split(band: np.ndarray, em: float) -> tuple[np.ndarray, np.ndarray] | None:
    """一条带是不是「左右两个方字」：能分栏，且两侧各自近方、宽 ≥ 0.25em。"""
    sp = _split_lr(band)
    if sp is None:
        return None
    for side in sp:
        ys = np.flatnonzero(side.any(1))
        x0, x1 = _xext(side)
        h, w = (ys[-1] - ys[0] + 1) if len(ys) else 0, x1 - x0
        if w < 0.25 * em or h / max(1, w) > PAIR_MAX_ASPECT:
            return None
    return sp


# ── 粘连密排的谷点切分 ────────────────────────────────────────────────────
def _run_pitch(sm: np.ndarray, base: float) -> float | None:
    """≥3 字长段的字距：投影自相关取够强（≥0.75 峰）的最小滞后，防 2 倍字距谐波。"""
    z = sm - sm.mean()
    ac = np.correlate(z, z, "full")[len(z) - 1:]
    lo, hi = int(0.4 * base), min(len(ac) - 1, int(1.4 * base))
    if hi <= lo or ac[0] <= 0:
        return None
    seg = ac[lo:hi]
    top = seg.max()
    peaks = [i for i in range(1, len(seg) - 1)
             if seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1] and seg[i] >= 0.75 * top]
    lag = lo + (peaks[0] if peaks else int(np.argmax(seg)))
    return float(lag) if ac[lag] > 0.15 * ac[0] else None


def _valley_split(m: np.ndarray, y0: int, y1: int, em: float,
                  hint: float | None = None) -> list[tuple[int, int]]:
    """把 [y0,y1) 按投影谷点切成 k 段；k 由 hint / 自相关 / 方字先验定。"""
    x0, x1 = _xext(m, y0, y1)
    w, h = x1 - x0, y1 - y0
    prof = m[y0:y1].sum(1).astype(float)
    sm = np.convolve(prof, np.ones(5) / 5, mode="same")
    base = max(w, 0.5 * em)
    p_est = hint or (_run_pitch(sm, base) if h > 3 * base else None)
    ks = ([max(2, int(round(h / p_est)))] if p_est
          else range(max(2, int(h / (1.35 * base))), int(h / (0.4 * base)) + 2))
    best = None
    for k in ks:
        pitch = h / k
        lo, hi = int(0.6 * pitch), int(1.45 * pitch)
        if lo < 1:
            continue
        cur: dict[int, tuple[float, list[int]]] = {0: (0.0, [])}
        for _ in range(k - 1):
            nxt: dict[int, tuple[float, list[int]]] = {}
            for pos, (c, cuts) in cur.items():
                for q in range(pos + lo, min(h - lo, pos + hi) + 1):
                    cc = c + sm[q] / max(1.0, w) + 0.5 * ((q - pos - pitch) / pitch) ** 2
                    if q not in nxt or cc < nxt[q][0]:
                        nxt[q] = (cc, cuts + [q])
            # 剪枝：每 3px 只留最优，DP 状态数随段高线性而不是平方
            thin: dict[int, tuple[int, tuple[float, list[int]]]] = {}
            for q, v in nxt.items():
                if q // 3 not in thin or v[0] < thin[q // 3][1][0]:
                    thin[q // 3] = (q, v)
            cur = {q: v for q, v in thin.values()}
            if not cur:
                break
        fin = [(c + 0.5 * ((h - pos - pitch) / pitch) ** 2, cuts)
               for pos, (c, cuts) in cur.items() if lo <= h - pos <= hi]
        if not fin:
            continue
        c, cuts = min(fin)
        c = c / k + 0.6 * abs(np.log(pitch / (0.95 * base)))   # 字近方形先验
        if best is None or c < best[0]:
            best = (c, cuts)
    if best is None:
        return [(y0, y1)]
    ys = [0] + best[1] + [h]
    return [(y0 + a, y0 + b) for a, b in zip(ys, ys[1:])]


def _full_square(t: list[int], em: float) -> bool:
    h, w = t[2] - t[0], t[3] - t[1]
    return 0.8 * em <= h <= 1.25 * em and 0.75 <= h / max(1, w) <= 1.3


# ── 雙行分栏 ─────────────────────────────────────────────────────────────
def _lr_sides(m: np.ndarray, y0: int, y1: int, em: float) -> tuple[list[RosterItem], list[RosterItem]] | None:
    """[y0,y1) 分左右两栏、各自递归切。分不开返回 None。"""
    sp = _split_lr(m[y0:y1])
    if sp is None:
        return None
    rm, lm = np.zeros_like(m), np.zeros_like(m)
    rm[y0:y1], lm[y0:y1] = sp
    rx, lx = _xext(rm), _xext(lm)
    return (_seg_mask(rm, min(em, 0.95 * (rx[1] - rx[0])), 1),
            _seg_mask(lm, min(em, 0.95 * (lx[1] - lx[0])), 1))


def _as_jiazhu(right: list[RosterItem], left: list[RosterItem]) -> list[RosterItem]:
    for it in right:
        it.kind = "jiazhu_a"
    for it in left:
        it.kind = "jiazhu_b"
    return right + left                                      # 雙行：右行读完再读左行


def _lr_runs(m: np.ndarray, groups: list[tuple[list[int], float | None]], em: float) -> list[tuple[int, int]]:
    """雙行段：相邻（缝 < RUN_GAP em）、分得出左右两侧的带连成一段，整段一起分栏。返回 [(起, 止)] 半开区间。

    雙行两行相位错开时，墨带有高有矮：高带按「高带分栏」切，夹在中间的矮带（左右各一字，vol01 p87 c9
    「林官」「士武」「文英」）不够高、凑不够 PAIR_RUN 条相位对齐，就被当成一个字，两字切成一格；一侧是窄字的带
    （p87 c7「士日」，「日」高宽比 1.7）过不了 `_pair_split`，把相位对齐段截断，段头「學筵」也成了一格。

    带分两档：强＝高带（> LR_MIN_H em）分得开，或矮带两侧都有整字宽（≥ LR_WIDE em，p88 c2 段头右「經筵」左「翰」），
    或过 `_pair_split`（两侧都是方字）；弱＝只是 `_split_lr` 分得开（「林」「鮑」这种左右结构的单字也算弱）。段的两头必须是强带，弱带只能夹在中间；段里有高带，或强带
    ≥ PAIR_RUN 条，才认。不看压扁密排段（hint）：雙行一条带左右两字并排、整条又扁又宽，会被 `_compressed_runs`
    认成压扁字。"""
    strong, weak = [], []
    for (y0, y1), _hint in groups:
        band = m[y0:y1]
        sp = _split_lr(band)
        weak.append(sp is not None)
        strong.append(sp is not None and (y1 - y0 > LR_MIN_H * em
                                          or min(_xext(side)[1] - _xext(side)[0] for side in sp) >= LR_WIDE * em
                                          or _pair_split(band, em) is not None))
    runs = []
    i = 0
    while i < len(groups):
        if not strong[i]:
            i += 1
            continue
        j = i + 1
        while j < len(groups) and weak[j] and groups[j][0][0] - groups[j - 1][0][1] < RUN_GAP * em:
            j += 1
        while j - 1 > i and not strong[j - 1]:          # 段尾退回到最后一条强带
            j -= 1
        tall = any(groups[q][0][1] - groups[q][0][0] > LR_MIN_H * em for q in range(i, j))
        if j - i >= 2 and (tall or sum(strong[i:j]) >= PAIR_RUN):
            runs.append((i, j))
        i = j
    return runs


def _flat_count(items: list[RosterItem]) -> int:
    """扁块数：高 < LR_FLAT × 宽（劈开的半个字是扁的；真字多近方，只有「一」「二」这类本来就扁）。"""
    return sum(it.y1 - it.y0 < LR_FLAT * (it.x1 - it.x0) for it in items)


def _lr_items(m: np.ndarray, y0: int, y1: int, em: float, chen: float | None) -> list[RosterItem] | None:
    """整段雙行分栏；两侧都 ≥2 字才认，否则 None（交回逐带处理）。

    整段分栏只该把「一格里并了左右两字」的框拆开。侧栏里字压得紧时，整段一起切会被投影谷点把一个字劈成两个
    扁块（全唐文 001 p35 c6 左行 28 字切成 46 格）。拿逐带处理的结果（`lr_run=False`）当底，整段分栏的扁块数
    比底多过 LR_FLAT_EXTRA 个就整段不认，回逐带处理。"""
    sides = _lr_sides(m, y0, y1, em)
    if sides is None or min(len(sides[0]), len(sides[1])) < 2:
        return None
    mm = np.zeros_like(m)
    mm[y0:y1] = m[y0:y1]
    if _flat_count(sides[0] + sides[1]) > _flat_count(_seg_mask(mm, em, 0, chen, lr_run=False)) + LR_FLAT_EXTRA:
        return None
    return _as_jiazhu(*sides)


# ── 递归主体 ─────────────────────────────────────────────────────────────
def _seg_mask(m: np.ndarray, em: float, depth: int = 0, chen: float | None = None,
              lr_run: bool = True) -> list[RosterItem]:
    out: list[RosterItem] = []
    col_x = _xext(m)
    bs = _bands(m)
    pitch = _compressed_runs(m, bs, em)
    # 压扁密排段的带原样保留（带着段字距）；其余带按段落成组各自并碎块
    groups: list[tuple[list[int], float | None]] = []
    buf: list[list[int]] = []
    for i, b in enumerate(bs):
        if i in pitch:
            groups += [(x, None) for x in _merge_frags(m, buf, em)]
            buf = []
            groups.append((b, pitch[i]))
        else:
            buf.append(b)
    groups += [(x, None) for x in _merge_frags(m, buf, em)]

    # 相位对齐的雙行：每条带里左右各一个小字，带本身不比一字高、上面的「高带分栏」不触发。
    # 连续 ≥ PAIR_RUN 条带都能分成两侧方字（不是「林」「鮑」那种窄偏旁）才认，单条不认。
    pair_sides = [(_pair_split(m[g[0][0]:g[0][1]], em) if depth == 0 else None) for g in groups]
    pair_run = [False] * len(groups)
    i = 0
    while i < len(groups):
        j = i
        while (j < len(groups) and pair_sides[j] is not None
               and (j == i or groups[j][0][0] - groups[j - 1][0][1] < RUN_GAP * em)):
            j += 1
        if j - i >= PAIR_RUN:
            for k in range(i, j):
                pair_run[k] = True
        i = max(j, i + 1)
    lr_end = dict(_lr_runs(m, groups, em)) if depth == 0 and lr_run else {}
    k = 0
    while k < len(groups):
        if k in lr_end:
            y0, y1 = groups[k][0][0], groups[lr_end[k] - 1][0][1]
            jz = _lr_items(m, y0, y1, em, chen)
            if jz is not None:
                out += jz
                k = lr_end[k]
                continue
        if pair_run[k]:
            right_items: list[RosterItem] = []
            left_items: list[RosterItem] = []
            while k < len(groups) and pair_run[k]:
                (y0, y1), _ = groups[k]
                for side, bucket in zip(pair_sides[k], (right_items, left_items)):
                    t = _tight(side, 0, y1 - y0)
                    if t is not None:
                        bucket.append(RosterItem(y0 + t[0], t[1], y0 + t[2], t[3]))
                k += 1
            for it in right_items:
                it.kind = "jiazhu_a"
            for it in left_items:
                it.kind = "jiazhu_b"
            out += right_items + left_items
            continue
        (y0, y1), hint = groups[k]
        k += 1
        h = y1 - y0
        x0, x1 = _xext(m, y0, y1)
        w = x1 - x0
        if depth == 0 and chen is not None and hint is None and h > SIDE_MIN_H * em:
            sp = _split_side_small(m[y0:y1], em, col_x, chen - y0)
            if sp is not None:
                for part in sp:
                    pm = np.zeros_like(m)
                    pm[y0:y1] = part
                    out += _seg_mask(pm, em, depth + 1)
                continue
        if depth == 0 and h > LR_MIN_H * em:
            sides = _lr_sides(m, y0, y1, em)
            if sides is not None:
                right, left = sides
                # 「臣」贴官衔末字：一侧只有它一个字。两侧都 ≥2 字就是雙行——字号不一定小
                # （vol01 p89 有中号字的雙行），不能拿字宽判
                if min(len(right), len(left)) >= 2:
                    out += _as_jiazhu(right, left)
                else:
                    out += sorted(right + left, key=lambda it: it.y0)
                continue
        if hint is not None:
            spans = _valley_split(m, y0, y1, em, hint) if h > 1.5 * hint else [(y0, y1)]
            guess = len(spans) > 1
        elif h > DENSE_H * max(w, 0.85 * em):
            spans = _valley_split(m, y0, y1, em)
            guess = True
        else:
            spans, guess = [(y0, y1)], False
        boxes = [t for t in (_tight(m, a, b) for a, b in spans) if t is not None]
        if guess and all(_full_square(t, em) for t in boxes):
            guess = False                 # 切出来的每块都是正常字号的方字（多是两字人名粘连），不算推的
        for t in boxes:
            out.append(RosterItem(t[0], t[1], t[2], t[3], "char", guess))
    return out


def _drop_isolated_specks(items: list[RosterItem], em: float) -> list[RosterItem]:
    """字距拉开的官衔段里，两字之间常有扫描墨点/短划（vol01 p103、p117 实测 38×22、40×12）。"""
    keep: list[RosterItem] = []
    for i, it in enumerate(items):
        if it.kind == "char" and max(it.y1 - it.y0, it.x1 - it.x0) < ISOLATED_SMALL * em:
            gap_up = it.y0 - items[i - 1].y1 if i > 0 else it.y0
            gap_dn = items[i + 1].y0 - it.y1 if i + 1 < len(items) else float("inf")
            if max(gap_up, gap_dn) >= ISOLATED_GAP * em:
                continue
        keep.append(it)
    return keep


def _drop_edge_bars(items: list[RosterItem], em: float, h_img: int) -> list[RosterItem]:
    """列图上下 EDGE_ZONE 内扁平的块是版框横条残段（写本框线粗细不匀、断续，`_clear_edge_bars` 按整行
    横跨认不全），不是字；「一」也扁，但不会贴着列端。"""
    zone = EDGE_ZONE * h_img
    return [it for it in items
            if not (it.y1 - it.y0 < EDGE_BAR_H * em and it.x1 - it.x0 > 2 * (it.y1 - it.y0)
                    and (it.y0 < zone or it.y1 > h_img - zone))]


def _column_flags(items: list[RosterItem]) -> list[str]:
    flags: list[str] = []
    if any(it.dense_guess for it in items):
        flags.append("roster_dense_guess")
    if any(it.kind != "char" for it in items):
        flags.append("roster_jiazhu")         # 雙行列：两行相位不齐、字小，vol01 只有 7 列，一律交人核
    body = [it for it in items if it.kind == "char"]
    if any(b.y0 < a.y1 for a, b in zip(body, body[1:])):
        flags.append("roster_overlap")        # 相邻两字 y 有重叠（多是「臣」贴着官衔末字），Step4 满宽裁会互相带墨
    if any(it.glyph is not None for it in items):
        flags.append("roster_glyph_refined")  # 有密排段按字形库重切过（books/siku_zongmu/roster_glyph）
    return flags


def _lead_in_jiazhu(items: list[RosterItem], em: float, col_x: tuple[int, int]) -> list[RosterItem]:
    """雙行段开头右行单独一个字（左行比右行晚半个字起，这一条带左边是空的）：窄（≤ LEAD_MAX_W 列宽）、靠右
    （中心在列中线右边）、下面紧接雙行，就是雙行右行的第一字，改 jiazhu_a（vol01 p88 c5/c6/c1 的「太」「太」「經」）。
    正文字占满列宽，「臣」在雙行段之后，都不会被误认。"""
    if not items:
        return items
    mid, width = (col_x[0] + col_x[1]) / 2, col_x[1] - col_x[0]
    k = 0
    while k < len(items) and items[k].kind == "char":
        k += 1
    if k == len(items) or items[k].kind != "jiazhu_a":
        return items
    j = k
    while j > 0:                                           # 从雙行段往上，连着的右靠窄字
        it, nxt = items[j - 1], items[j]
        if (it.kind == "char" and it.x1 - it.x0 <= LEAD_MAX_W * width and (it.x0 + it.x1) / 2 > mid
                and nxt.y0 - it.y1 < RUN_GAP * em):
            j -= 1
        else:
            break
    for it in items[j:k]:
        it.kind = "jiazhu_a"
    return items


def segment_roster_column(ink: np.ndarray, em: float, chen: float | None = None) -> RosterColumn:
    """一列（已 prepare 过的墨 mask）→ 读序排好的字。给了全页「臣」行 `chen`，再拆贴着邻字的偏右小字。"""
    items = [it for it in _seg_mask(ink, em, chen=chen)
             if max(it.y1 - it.y0, it.x1 - it.x0) >= SPECK * em]
    items = _drop_isolated_specks(items, em)
    items = _drop_edge_bars(items, em, ink.shape[0])
    items = _lead_in_jiazhu(items, em, _xext(ink))
    return RosterColumn(items=items, em=em, flags=_column_flags(items))


def _chen_row(cols: list[RosterColumn], prepared: list[tuple[np.ndarray, float]],
              xs: list[float], em: float) -> float | None:
    """全页「臣」行：各列第一个「偏右小字」（宽 < 0.6em、中心在列右 45%、位于列下 60%）y 的中位数。"""
    ys: list[int] = []
    for rc, (ink, width), x0 in zip(cols, prepared, xs):
        h = ink.shape[0]
        for it in rc.items:
            if (it.kind == "char" and it.x1 - it.x0 < 0.6 * em
                    and (it.x0 + it.x1) / 2 > x0 + 0.55 * width and it.y0 > 0.4 * h):
                ys.append(it.y0)
                break
    return float(np.median(ys)) if ys else None


def _glyph_refine(rc: RosterColumn, ink: np.ndarray, chen_row: float, scorer) -> None:
    """官衔区（「臣」行以上）≥ RUN_MIN_EM 的连续密排段按字形库重切，就地改 rc。雙行列不碰。

    只修「疑似两字合一」的段：段内几何切出的片至少 MERGED_MIN 个比一字高（> MERGED_H × em），
    或带 dense_guess。正常字号段几何本来就切对了，交给库反而会把上下结构字劈开
    （正→一止、主→一上、走→一史，vol01 p89/119/95 实测）；单个高块多半是字下挂了墨点（p119「部」）。
    采纳闸：库切法的片平均相似度要比几何切法高 ACCEPT_GAIN。整段切而不是逐片切——逐片切实测更差
    （段内正常字给 DP 当字距参照）。"""
    from .roster_glyph import ACCEPT_GAIN, MERGED_H, MERGED_MIN, RUN_GAP_EM, RUN_MIN_EM, glyph_dp
    em = rc.em
    if any(it.kind != "char" for it in rc.items):
        return
    runs: list[list[int]] = []
    for b in _bands(ink):
        if runs and b[0] - runs[-1][1] < RUN_GAP_EM * em:
            runs[-1][1] = b[1]
        else:
            runs.append(list(b))
    items = list(rc.items)
    for a, b in runs:
        b = min(b, int(chen_row - 0.15 * em))
        if b - a < RUN_MIN_EM * em:
            continue
        inside = [it for it in items if a <= (it.y0 + it.y1) / 2 <= b]
        if not inside:
            continue
        b = max(b, max(it.y1 for it in inside))          # 被截线切到的格整格纳入，免得半格重切
        n_tall = sum(it.y1 - it.y0 > MERGED_H * em for it in inside)
        if n_tall < MERGED_MIN and not any(it.dense_guess for it in inside):
            continue
        x0, x1 = min(it.x0 for it in inside), max(it.x1 for it in inside)
        segs = glyph_dp(ink, a, b, x0, x1, scorer)
        if not segs:
            continue
        geo = scorer.best([ink[it.y0:it.y1, x0:x1] for it in inside])
        if np.mean([s for *_, s in segs]) - np.mean([s for s, _ in geo]) < ACCEPT_GAIN:
            continue
        sub = np.zeros_like(ink)
        sub[:, x0:x1] = ink[:, x0:x1]
        new = []
        for y0, y1, ch, _sim in segs:
            t = _tight(sub, y0, y1)
            if t is not None:
                new.append(RosterItem(t[0], t[1], t[2], t[3], "char", False, ch))
        k = items.index(inside[0])
        items = items[:k] + new + [it for it in items[k:] if it not in inside]
    rc.items = items
    rc.flags = _column_flags(items)


def segment_roster_page(cols: list[tuple[np.ndarray, tuple[float, float] | None]],
                        ink_threshold: int = 128, scorer=None) -> list[RosterColumn]:
    """整页：先量全页 em，再逐列切。cols = [(列图灰度, content_x)]。

    给了 `scorer`（`roster_glyph.GlyphScorer`）就再把官衔区的连续密排段按本书字形库重切
    （overview#450：p90 类压扁粘连字，几何数不准字数）。"""
    prepared = [prepare(g, cx, ink_threshold) for g, cx in cols]
    em_page = page_em(prepared)
    ems = [em_page or 0.65 * width for _ink, width in prepared]
    out = [segment_roster_column(ink, em) for (ink, _w), em in zip(prepared, ems)]
    if not out:
        return out
    xs = [float(cx[0]) if cx is not None else 0.0 for _, cx in cols]
    chen = _chen_row(out, prepared, xs, em_page or out[0].em)
    if chen is not None:
        # 第二遍：写本的「臣」斜贴邻字、和官衔末字或人名首字粘成一带（史記文淵閣本职名页），
        # 第一遍从自成一带的「臣」量出全页臣行，再按它把贴着的拆出来
        out = [segment_roster_column(ink, em, chen) for (ink, _w), em in zip(prepared, ems)]
    if scorer is not None and chen is not None:
        for rc, (ink, _w) in zip(out, prepared):
            _glyph_refine(rc, ink, chen, scorer)
    return out
