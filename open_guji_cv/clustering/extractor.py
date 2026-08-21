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

PADDING_RATIO = 0.08
MIN_INK_RATIO = 0.01
RULE_LINE_FRAC = 0.6       # 贯穿格位的线状墨迹占比超此 → 标 rule_like（仅提示）

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


def _rule_line_fraction(gray: np.ndarray) -> float:
    """墨迹中「贯穿整个格位的细直线」所占比例。

    界行竖线与版框横线渗入空格位时，连通体会从格位一端通到另一端且
    在另一维度极细；正常字符受字距约束，笔画不会贯穿整格。图块存的是
    完整格位（含 8% 纵向外扩），几何信息完好——判定必须在这里做，
    归一化之后细线被各向异性拉伸，证据就没了。
    """
    if gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    total = int(np.count_nonzero(binary))
    if total < 10:
        return 0.0
    h, w = binary.shape
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    line_area = 0
    for x, y, cw, ch, area in stats[1:]:
        if (ch >= 0.95 * h and cw <= 0.25 * w) or \
           (cw >= 0.95 * w and ch <= 0.20 * h):
            line_area += int(area)
    return line_area / total


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

            # 水平方向内缩——列边界即界行位置；纵向条带覆盖全部格位并留出
            # 出头笔画的余量，界行竖线要整条进条带才认得出「高且窄」。
            shrink_x = min(col_w * 0.03, 4.0)
            sx0 = int(round(max(0.0, left_x + shrink_x)))
            sx1 = int(round(min(float(img_w), right_x - shrink_x)))
            pad_y = cell_h_ref * self.padding_ratio
            sy0 = int(round(max(0.0, min(float(c["y_top"]) for c in cells) - pad_y)))
            sy1 = int(round(min(float(img_h),
                               max(float(c["y_bottom"]) for c in cells) + pad_y)))
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            strip = page_img[sy0:sy1, sx0:sx1]

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

                x0 = float(sx0)
                x1 = float(sx1)
                py0 = float(sy0 + y0)
                py1 = float(sy0 + y1)

                ink = _patch_ink_ratio(patch)
                flags: list[str] = []
                if (owner is not None and box is None) or ink < self.min_ink_ratio:
                    flags.append("suspect_empty")
                if _rule_line_fraction(patch) >= RULE_LINE_FRAC:
                    # 格内墨迹主要是贯穿格位的直线（界行/版框渗入空格位）。
                    # 只作提示不作删除：真「一」的横笔也可能贯穿格宽，
                    # 实测二者分布重叠，阈值须由人工审查反馈标定。
                    flags.append("rule_like")
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

                page_patch_dir = out_dir / "patches" / page
                page_patch_dir.mkdir(parents=True, exist_ok=True)
                for inst, patch in self.extract_page(page_img, grid, book, page):
                    imwrite(str(out_dir / inst.patch_path), patch)
                    index_f.write(inst.to_json() + "\n")
                    n_chars += 1
                    if inst.flags:
                        n_flagged += 1
                n_pages += 1

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
