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
TIGHT_MARGIN = 2           # 裁紧余量：图块=本字墨迹外接框 ± 此像素
                           # （2026-08-24 用户定版：框要完完全全包住字即可，
                           # 左右贴墙的空白装的从来不是字，是边框残渣）
BOUNDARY_BAND = 0.10       # 图块上下各此比例的高度算「边缘带」
BOUNDARY_INK_T = 0.025     # （旧判据，_boundary_ink_frac 保留供研究脚本）
BOUNDARY_BOT_T = 0.025     # 下带墨占比超此 → boundary_ink（正信号带；
                           # 0.015 档在 vol02 抽样里大量标到贴底满格字，
                           # 取 0.025 两册兼顾——见 boundary_ink 定版记录）
BOUNDARY_TOP_T = 0.08      # 上带逃生口：超此才报（上带整体是反信号）

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
# ── 首/末格外的边框横条掩蔽 ──────────────────────────────
# 用户审阅实测：首字含上框横线、末字含下框横线成批出现。横条作为独立
# 连通体被 _assign_column 归给最近的首/末格，再随 padding/归属外扩进
# 图块。完全落在首格上沿之上/末格下沿之下的扁平满宽连通体只能是版框
# 横线——从条带里抹掉。「一」字有位置保护：它在自己格内，不可能整体
# 越出首末格界；贴着字的横线（连通）不动，保守优先。
FRAME_BAR_ROW_T = 0.55     # 行墨 ≥ 此比例 × 条带宽 → 横条候选行。「一/百顶横」
                           # 也能到 0.6——单看形状分不开，页级延续探针才是闸门
FRAME_BAR_SOFT_T = 0.35    # 迟滞：确认行 ±3 行内 ≥ 此比例的行一并算横条
                           # （波浪线边缘行是部分填充）
FRAME_BAR_ZONE = 0.30      # 只看首格上沿 +/末格下沿 − 此比例 × 格高的端区
                           # （页级共识网格与本页物理框有相位差，横条常在
                           # 末格**内部**尾段，实测 vol02/136 在末线上方 25px）
FRAME_BAR_GAP_FILL = 0.6   # 空档异常行：单侧空档被填满这个比例 → 横条候选
FRAME_BAR_GAP_MED = 0.15   # ……但该侧空档**常年**墨率中位超此值就不算异常
                           #   （界行竖线落在档里时每行都满，那是线不是条）
FRAME_BAR_GAP_MAX_H = 0.35 # ……且异常连续段高 ≤ 此比例 × 格高（条是薄的，字不是）
FRAME_BAR_SIDE_T = 0.5     # 「横条行」的定谳证据：**文字带两侧的墙内空档**
                           # 里该行的墨比 ≥ 此值。字的笔画到文字带边就停
                           # （「一/辶捺/灬底」都如此），空档里只有横条/
                           # 细界行会有墨（界行 ~3px / 空档 ~25px ≈ 0.12，
                           # 够不着）。第一版用页级远窗探针，被**邻列同一
                           # 行字**的墨骗了——各列末行字同 y 对齐，探出去
                           # 撞到的「延续」是隔壁的字，末格宽底笔被成片
                           # 误削（实测 vol01 274 格核心区被削 ≥250px）
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
JIAZHU_SPAN_T = 0.75       # 两个子列合起来占**列距**的比例下限。实测两册
                           # 抽样 4023 个格：普通字的跨度/列距中位 0.59、
                           # 95 分位 0.676，夹注在 0.78~0.97。0.85 会漏掉
                           # 写得略窄的夹注（vol01/184 col9「陰陽五行／
                           # 相宅相墓」量到 0.785，用户 r6 报过）；下调到
                           # 0.75 后 vol01/36「如」、vol02/74「外」、
                           # vol01/92「韶」、vol02/144「郭」这些左右结构
                           # 仍全部拒判，抽样 30 页拆出的列数一格没变。
JIAZHU_GAP_MIN = 3         # 子列间缝宽下限（px）。部首缝只有 2~3px
JIAZHU_MASS_W = 0.6        # 单个子列宽度上限（× 列宽）
JIAZHU_ALIGN = 8           # 相邻格的缝中心相差不超过此才算同一条夹注（px）
JIAZHU_MIN_RUN = 2         # 至少连续这么多格才判夹注
JIAZHU_CC_MIN = 500        # 段中位「两侧较小 maxCC」低于此 → 噪点段否决
# ── 段端收编（2026-08-26 用户 r10：「双行小注有时奇数个字，最后一行
# 剩一个，要识别出这是小注在 a 行，而不是正文」）──────────────────
# 单格判据永远量不出末行：奇数字的末行只有右半一个字（span 只有半列，
# 过不了 JIAZHU_SPAN_T）；偶数字的末行两个小字合起来也常不够跨度。
# 桥接也救不了段端——只有一侧邻格。收编拿**邻格的缝中心**当尺：
#   单字尾   墨 ≥JZ_TAIL_A_FRAC 在缝右（a 侧）且 a 侧够窄 → 只发 a 半
#   漏拆行   缝两侧各有实墨、缝带内几乎无墨、两半各自够窄 → 正常拆 a/b
# 全尺寸正文窄字（大/督/撫）居中，frac_a≈0.5、缝带上有墨，两条都过不了。
JZ_TAIL_MIN_INK = 100      # 收编候选的总墨下限（px）
JZ_TAIL_A_FRAC = 0.8       # 单字尾：缝右墨占比下限
JZ_TAIL_GAP_BAND = 3       # 缝带半宽（px）
JZ_TAIL_GAP_FRAC = 0.02    # 缝带内墨占比上限（正文字的中竖会露馅）
JZ_ROW_B_CC = 250          # 分型看 b 侧最大连通体：≥此是真笔画（「一」实测
                           # ~700+）→ 整行拆分；<此只是邻字残渣 → 单字尾。
                           # 拿墨占比分型栽过：vol02/4:5:20 末行「一|璉」的
                           # 「一」只占 18% 墨，被 0.8 的比例判据划成残渣，
                           # b 半被压制、「一」被丢——红线事故。        # 墨的横向重心偏离格心超此比例 → 疑似横向截断
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
    sub: str | None = None                    # 夹注子列："a"=右 / "b"=左；正文 None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "CharInstance":
        d = json.loads(line)
        d["bbox"] = tuple(d["bbox"])
        # 只取已声明字段：index.jsonl 可能带后加的溯源键，未知键不应炸
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


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
    # 疑似：下带见墨（缺陷几乎全从下方来）；top 只留高位逃生口
    # ——上带是反信号（clean 悬顶字），详见 _boundary_band_fracs
    top, bot = _boundary_band_fracs(gray)
    if bot > BOUNDARY_BOT_T or top > BOUNDARY_TOP_T:
        flags.append("boundary_ink")
    return flags



# ── 自检队列口径（2026-08-25，用户 r7「有一个自检太多了 我就没消除」）─
# flags 里混着两种东西：**缺陷**（这一格可能切错了，要人看）和**版式
# 标注**（这一格是什么，给下游用）。jiazhu 是后者——本批 18 页 21 条
# jiazhu 里用户一条都没判错，它进自检队列纯粹是让人白清一遍。
# 标注照旧写进 flags（下游按它把夹注图块隔离成单例），只是不再计入
# 「待审」的口径。
INFO_FLAGS = frozenset({"jiazhu"})


def defect_flags(flags) -> list[str]:
    """flags 里真正代表「可能切错了」的那几个（见 INFO_FLAGS 注释）。"""
    return [f for f in (flags or ()) if f not in INFO_FLAGS]


def _jiazhu_gap_center(gray: np.ndarray,
                      ref_w: float | None = None) -> tuple[float, float] | None:
    """图块若呈「双列小字」形态，返回 (两子列间缝的中心 x, strength)。

    判据（实测 vol02 版本注「永樂大典本/通志堂本」与 vol01 职名双行结衔）：
    墨的总跨度占满列宽（span ≥ JIAZHU_SPAN_T——夹注两个子列合起来和正文
    一样宽，单字只占 ~0.7）、中缝 ≥ JIAZHU_GAP_MIN px（部首缝只有 2~3px）、
    两侧墨量均衡、单侧不超过 0.6 跨度。

    ref_w 是量跨度用的**尺子**，取**列距**（period）；不给就退回图块宽度。

    两个都不能用：
    - 图块宽度：条带宽度按界行/空白缝定，同一页各列能差 50px，宽缝
      补齐（_widen_wide_gutters）之后差得更多——vol02/171 col2 的窗口
      从 150px 补到 202px，同一段夹注的 span 比就从 0.88 掉到 0.83，
      整段夹注反而判不出来了。
    - 文字带宽度：文字带的**定义**就是「正常居中字的范围」，任何一个
      正常字的跨度除以它都接近 1，判据直接失效——试过一版，vol01 的
      夹注列从 10 列涨到 36 列，涨出来的全是「如=女+口」「外=卜+夕」
      「頗=皮+頁」这种左右结构被拦腰劈开。
    列距是书级刚性常量，又恰好接近原先标定用的图块宽度，两头都占。

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
    span = x1 - x0 + 1
    if span / float(ref_w or w) < JIAZHU_SPAN_T:
        return None
    runs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(xp[x0:x1 + 1]):
        if v == 0 and start is None:
            start = i
        elif v > 0 and start is not None:
            runs.append((start, i)); start = None
    # 缝要在**墨迹跨度**的中段，不是图块的中段——图块两侧的留白多少
    # 由条带宽度决定，拿它定中段会随窗口宽窄漂移
    gaps = [(a, b) for a, b in runs
            if a > span * 0.30 and b < span * 0.70
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
    if max(left.shape[1], right.shape[1]) > JIAZHU_MASS_W * span:
        return None
    # strength：两侧较小的最大连通体面积。真小字必有笔画网络级大连通
    # 体（实测 ≥1242px），纸面噪点全是碎点（≤327px）——单格不卡（薄字
    # 「一/三」会误伤），由 flag_jiazhu_runs 按段中位数否决噪点段。
    strength = w * h
    for side in (left, right):
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(
            np.ascontiguousarray(side))
        strength = min(strength,
                       int(stats[1:, 4].max()) if n > 1 else 0)
    return float(x0 + (ga + gb) / 2), float(strength)


def flag_jiazhu_runs(
        entries: list[tuple[int, tuple[float, float] | None]]
        ) -> dict[int, float]:
    """列内连续、缝对齐的夹注格 → 缝中心。
    entries: [(idx, (gap_center, strength)|None)]。

    桥接：夹注段里个别行（vol02/5「一/辨」）单侧墨太少，单格判据因
    均衡不足落空，会把连段拦腰截断——两侧紧邻格的缝中心都在且对齐时，
    这一格按邻格中心均值补上（一次只桥 1 格，两侧必须是实测中心，
    防止桥接自我扩散）。返回值里桥接格给的就是这个插值中心，拆分
    a/b 时直接用。

    噪点段否决：纸面碎点列（vol01/3 col2）span/缝/均衡全能骗过、还能
    连成 7 格长段，唯一分得开的是连通体结构——真小字必有笔画网络级
    大连通体（两侧较小 maxCC ≥1242px 实测），噪点全是碎点（≤327px）。
    按**段中位数** < JIAZHU_CC_MIN 整段否决（单格不卡，薄字「一/三」
    由段里其他字撑住中位数）。
    """
    ents = sorted(entries)
    measured = {i: c for i, c in ents if c is not None}
    cmap: dict[int, float] = {i: c[0] for i, c in measured.items()}
    smap: dict[int, float] = {i: c[1] for i, c in measured.items()}
    for i, c in ents:
        if c is not None:
            continue
        a, b = measured.get(i - 1), measured.get(i + 1)
        if a is not None and b is not None and abs(a[0] - b[0]) <= JIAZHU_ALIGN:
            cmap[i] = (a[0] + b[0]) / 2
    out: dict[int, float] = {}

    def _commit(run: list[int]) -> None:
        if len(run) < JIAZHU_MIN_RUN:
            return
        strengths = sorted(smap[j] for j in run if j in smap)
        if not strengths or strengths[len(strengths) // 2] < JIAZHU_CC_MIN:
            return
        out.update({j: cmap[j] for j in run})

    run: list[int] = []
    prev_i = None
    for i in sorted(cmap):
        ok = (prev_i is not None and i == prev_i + 1
              and abs(cmap[i] - cmap[prev_i]) <= JIAZHU_ALIGN)
        if ok:
            run.append(i)
        else:
            _commit(run)
            run = [i]
        prev_i = i
    _commit(run)
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


def _boundary_band_fracs(gray: np.ndarray) -> tuple[float, float]:
    """上带、下带各自的墨量占比（分开算——两带不是一种东西）。

    2026-08-25 调查（split_curve_boundary_research.md 任务C）：clean 字
    在格里**悬顶**，上带见墨的主体是高字/顶横（top>0.02 精确率只有
    33%，反信号）；缺陷几乎全从**下方**来——列尾版框横线、grid_shift
    下坠、下邻字残余（bot>0.01 精确率 61.5%）。合并成一个比例等于拿
    反信号稀释正信号。
    """
    if gray.size == 0:
        return 0.0, 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = gray < BINARY_THRESHOLD_PATCH
    total = int(binary.sum())
    if total == 0:
        return 0.0, 0.0
    band = max(2, int(binary.shape[0] * BOUNDARY_BAND))
    return (int(binary[:band].sum()) / total,
            int(binary[-band:].sum()) / total)


def _runs(ys: np.ndarray) -> list[tuple[int, int]]:
    """把递增行号切成连续段 [(起, 止), ...]（含两端）。"""
    out: list[tuple[int, int]] = []
    if not len(ys):
        return out
    s = p = int(ys[0])
    for y in ys[1:]:
        y = int(y)
        if y != p + 1:
            out.append((s, p))
            s = y
        p = y
    out.append((s, p))
    return out


def mask_frame_bars_outside(strip: np.ndarray,
                            local: list[tuple[int, float, float]],
                            lpad: int, rpad: int,
                            cell_h: float,
                            right_ext: int = 0,
                            left_ext: int = 0) -> np.ndarray:
    """抹掉条带首/末端区里的版框横线**行**（用户审阅反馈的主病灶）。

    三道判据缺一不可：
    - 按**行**不按连通体：横条经 8 连通与条带边缘细碎渣会链成几百像素
      高的稀疏大连通体（实测 vol02/136 col5 高 614px、墨才 2970），
      任何「扁平连通体」判据都失灵；
    - 端区限定：页级共识网格与本页物理框有相位差，下框横条常在末格
      **内部**尾段（实测在末线上方 25px），所以端区伸进格内 0.3 格；
    - **墙内空档**定谳（lpad/rpad = 文字带相对条带的左右起止）：横条
      填满文字带两侧的空档，字的宽底笔（一/辶捺/灬底）到文字带边就停
      （见 FRAME_BAR_SIDE_T 注——页级探针会被邻列同行字骗，已废）。
    只按行抹、只在端区抹：与字连通的横条也只削掉横条本身那几行，
    绝不顺着连通关系动格心的字身。"""
    if not local:
        return strip
    top = int(min(l for _, l, _ in local))
    bot = int(max(b for _, _, b in local))
    H, W = strip.shape
    # 左右缘救援外扩带（left_ext/right_ext）不算「墙内空档」：那里按
    # 设计装着被救回的穿边笔尖 + 磨损界行点渣。r11 实测 vol01/34
    # 「類」——底横的笔尖伸进右外扩带，被当成「横条填满右侧空档」的
    # 证据，整条底横带（30 行）被抹掉、字身裂成两半（红线）。取证窗
    # 与行墨统计都止步于外扩前的裁切边，两侧同理。
    We = max(0, W - right_ext)
    Ws = min(left_ext, We)
    la, lb = Ws, max(Ws, min(lpad - 2, We))
    ra, rb = min(We, rpad + 2), We
    if (lb - la) + (rb - ra) < 8:      # 没有空档可取证 → 保守不动
        return strip
    binary = (strip < BINARY_THRESHOLD_PATCH)
    rowink = binary[:, Ws:We].sum(axis=1)
    z = int(FRAME_BAR_ZONE * cell_h)
    zone = np.zeros(H, dtype=bool)
    zone[0:np.clip(top + z, 0, H)] = True
    zone[np.clip(bot - z, 0, H):H] = True
    # 空档异常行（2026-08-26 自评 r2 的无声漏网 vol01/48:3:0）：版框横条
    # 常是**阶梯形**——一端厚一端薄。行墨门槛只抓得住薄段（横贯全宽），
    # 厚段那几行行墨才 26% 条带宽，够不着 55%，于是厚块留在图块里、与字
    # 连成一体，还不带任何旗。厚段的特征换个地方看就很显眼：它**把一侧
    # 空档填满**，而空档常年是空的（该条实测中位 0.000、最大 0.83）。
    # 用「本条自己的中位数」自归一，界行竖线落在档里的情形自动排除
    # （那种每行都满，中位数就高）。再要求异常段**薄**，字不会中招。
    gap_rows = np.zeros(H, dtype=bool)
    for ga, gb in ((la, lb), (ra, rb)):
        if gb - ga < 6:
            continue
        g = binary[:, ga:gb].mean(axis=1)
        if float(np.median(g)) > FRAME_BAR_GAP_MED:
            continue
        ys = np.flatnonzero(g >= FRAME_BAR_GAP_FILL)
        if not ys.size:
            continue
        for a, b in _runs(ys):
            if b - a + 1 <= FRAME_BAR_GAP_MAX_H * cell_h:
                gap_rows[a:b + 1] = True
    core = (rowink >= FRAME_BAR_ROW_T * (We - Ws)) & zone
    if not core.any() and not (gap_rows & zone).any():
        return strip
    wiped = np.zeros(H, dtype=bool)
    for y in np.flatnonzero(core):
        lf = float(binary[y, la:lb].mean()) if lb > la else 0.0
        rf = float(binary[y, ra:rb].mean()) if rb > ra else 0.0
        if max(lf, rf) >= FRAME_BAR_SIDE_T:
            wiped[y] = True
    if not wiped.any() and not (gap_rows & zone).any():
        return strip
    soft = (rowink >= FRAME_BAR_SOFT_T * (We - Ws)) & zone
    for _ in range(2):
        for y in np.flatnonzero(soft & ~wiped):
            if wiped[max(0, y - 3):y + 4].any():
                wiped[y] = True
    # 穿行保护（用户实审反馈：字的捺/底笔常压在框线行上，整行抹会把
    # 穿行而过的笔画一起削掉）：对每条抹带逐 x 检查，[带±5行] 里的墨
    # 高出带高 ≥6px 的 x 是贯穿笔画，保留；只有带内有墨的 x 是纯横条，
    # 抹。「只裁横条本身，不动与它连通的字」。
    out = strip.copy()
    # 空档异常段：**不按行整抹**。厚条有十几行厚，行抹的穿行保护会把它
    # 当成穿行笔画放过（保护门槛是「墨高出带高 6px」，条自己就够厚）。
    # 改成在这几行的**横切片**里做连通体分析，只抹「从空档连出来」的那
    # 一块——字的笔画到文字带边就停，不会从空档里长出来。
    for ga, gb in _runs(np.flatnonzero(gap_rows & zone)):
        slab = binary[ga:gb + 1]
        ns, ls, sst, _ = cv2.connectedComponentsWithStats(
            slab.astype(np.uint8), 8)
        for k in range(1, ns):
            x, _y, w, _h, _a = sst[k]
            touches_gap = (x < lb and lb > la) or (x + w > ra and rb > ra)
            if touches_gap:
                out_slab = out[ga:gb + 1]
                out_slab[ls == k] = 255
    ys = np.flatnonzero(wiped)
    if not ys.size:
        return out
    bands = []
    s = ys[0]
    for a, b2 in zip(ys, ys[1:]):
        if b2 - a > 1:
            bands.append((s, a + 1)); s = b2
    bands.append((s, ys[-1] + 1))
    for ya, yb in bands:
        ea, eb = max(0, ya - 5), min(H, yb + 5)
        span_ink = binary[ea:eb].sum(axis=0)
        protect = span_ink >= (yb - ya) + 6
        seg = out[ya:yb]
        seg[:, ~protect] = 255
    return out


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


# ── 格界碎渣带剥离（2026-08-25 朱批第二轮回流）───────────
# 磨损下框碎成**点状虚线**（行墨稀到过不了横条掩蔽的行判据），列尾格
# 的字下方混进一排碎渣，裁紧时被框进图块（用户实审 15 例：上於均淵第
# 無以其/久至四人職分朕 全是好字 + 底部虚线）。判据的要害是**位置**：
# 碎渣带骑在**格界线**上（框线的物理位置，裁前坐标已知），而字的灬点
# 再低也在格界上方十几像素——尺寸判据分不开两者（虚线段 h4-7 但宽到
# 37px、墨 194；灬点 12×15 墨 ~120），位置判据一刀两断。只剥独立
# 连通体（与字连通的墨绝不动——用户红线），且 ≥2 个成带才剥。
SPECKLE_ZONE = 8           # 格界 ± 此像素内为碎渣带
SPECKLE_H = 15             # 碎渣连通体高度上限（框线渣扁平，字身高得多）
SPECKLE_AREA = 300         # 碎渣连通体墨量上限
SPECKLE_MIN_N = 2          # 带内 ≥ 此数才剥（孤立墨渍不动，宁留勿删）


def strip_speckle_band(patch: np.ndarray, cell_top: float,
                       cell_bot: float) -> np.ndarray:
    """剥掉骑在格界线上的碎渣带。cell_top/cell_bot 为图块坐标系里的格界。"""
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return patch
    hits = []
    for k in range(1, n):
        y, h, area = int(st[k, 1]), int(st[k, 3]), int(st[k, 4])
        if h > SPECKLE_H or area > SPECKLE_AREA:
            continue
        cy = y + h / 2.0
        # 非对称：下界取「线上及以下」（框渣骑线、邻字顶尖越线），上界
        # 取「线上及以上」。字的灬点/底横离格界还有 ≥8px，不会进带。
        if cy >= cell_bot - 2 or cy <= cell_top + 2:
            hits.append(k)
    if len(hits) < SPECKLE_MIN_N:
        return patch
    out = patch.copy()
    for k in hits:
        out[lab == k] = 255
    return out


# ── 列端框渣剥离（2026-08-25，用户 r4 实审定口径）────────
# 用户 r4 实审 153 格：86 个判错里 61 个（71%）是**列末格带下边框**——
# 字本身完整，只是版框横线离末字太近，格框一裁必然带进来。用户定的
# 口径是「后期算法消掉它就不算错误截取」，于是这里把框渣当**可后处理
# 的污染**剥掉，而不再要求切分层做到框线不进图块（物理上做不到）。
#
# 判别（r4 的 415 个残余块 vs 46 个 OK 图块里的字身部件标定）：
#   与字身主体的垂直间隙   残余 p50=5px / p90=23px；字部件 p90=2px ← 最强
#   尺寸                   残余 p50 面积 3px、高 1px；字部件 p50 面积 371、高 27
# 「灬」的四点、「二」的下横这类字身部件**紧贴**字身（间隙 ≤2px），
# 用间隙闸就能保住；框渣离字身远。红线（用户定）：只剥与字身**不连通**
# 的独立连通体，绝不碰与字身连通的墨——框线与字粘连的那些剥不掉，
# 保留并由 frame_bars / boundary_ink 标记送审。
DEBRIS_ZONE = 0.18         # 只在格界外侧此比例（× 格高）的带内剥
DEBRIS_GAP = 0.025         # 与字身主体的最小间隙（× 格高，~3px@120px 格）
DEBRIS_AREA = 120          # 残渣墨量上限（px）
DEBRIS_H = 0.05            # 或高度上限（× 格高）


def strip_frame_debris(patch: np.ndarray, cell_top: float,
                       cell_bot: float, cell_h: float) -> np.ndarray:
    """剥掉列端格上下边缘带里与字身分离的框线碎渣。

    cell_top/cell_bot 为格界在图块坐标系里的位置。只应对列首/列尾格
    调用——中段格没有版框，那里的边缘墨是邻字残余，归切分层管。
    """
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return patch
    areas = st[1:, 4]
    main = int(np.argmax(areas)) + 1          # 字身 = 最大连通体
    m_y0, m_y1 = int(st[main, 1]), int(st[main, 1] + st[main, 3])
    zone = DEBRIS_ZONE * cell_h
    gap_min = DEBRIS_GAP * cell_h
    h_max = DEBRIS_H * cell_h
    hits = []
    for k in range(1, n):
        if k == main:
            continue
        y, ch, area = int(st[k, 1]), int(st[k, 3]), int(st[k, 4])
        y1 = y + ch
        in_bot = y1 >= cell_bot - zone
        in_top = y <= cell_top + zone
        if not (in_bot or in_top):
            continue
        gap = (y - m_y1) if y >= m_y1 else (m_y0 - y1)
        if gap < gap_min:                     # 紧贴字身 → 是字的部件
            continue
        if area > DEBRIS_AREA and ch > h_max:
            continue                          # 又大又高 → 不是碎渣，留着送审
        hits.append(k)
    if not hits:
        return patch
    out = patch.copy()
    for k in hits:
        out[lab == k] = 255
    return out


# ── 版框断段剥离（2026-08-25，用户问「还有没有别的办法」）────
# 曲线切边之后仍剩下一类框渣：版框横线被字挡断后留在字**左右两侧**的
# 断段。它们与字身垂直位置重叠，所以曲线路径（必须走在字身之下）够不
# 着，间隙判据（gap≥1）也失效——两组的面积/高度/宽高比/填充率分布全部
# 重叠，图块内部再怎么量都分不开。
#
# 分得开的信息在**图块之外**：框线横贯整版，被字挡断只是局部现象，
# 断段所在的那几行在**列框外侧仍然继续走**；字的笔画到界行就停。实测
# 列外墨率（取左右两侧的较大者，因为被挡断的那一侧本来就没墨）——
# 框线断段 0.46~0.66，「黙」的四点底这类字部件 ≤0.24，一刀两断。
STUB_SIDE_PROBE = 42       # 列框外侧的探测宽度（px）
STUB_SIDE_INK = 0.35       # 列外墨率（取两侧较大者）超此 → 框线在继续
STUB_MAX_H = 12            # 断段的高度上限（px）——版框线本来就薄
STUB_MIN_AREA = 40         # 小于此的碎点交给别的闸，这里不管


def strip_frame_stub(patch: np.ndarray, page: np.ndarray,
                     x0: int, x1: int, y0: int) -> np.ndarray:
    """剥掉版框横线被字挡断后留下的断段（判据见上方注释）。

    x0/x1 是本列在整页上的左右边界，y0 是图块顶在整页上的 y。
    """
    if page.size == 0 or patch.size == 0:
        return patch
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return patch
    main = int(np.argmax(st[1:, 4])) + 1
    H, W = page.shape[:2]
    hits = []
    for k in range(1, n):
        if k == main:
            continue
        ch, area = int(st[k, 3]), int(st[k, 4])
        if ch > STUB_MAX_H or area < STUB_MIN_AREA:
            continue
        ya = max(0, y0 + int(st[k, 1]))
        yb = min(H, ya + ch)
        if yb <= ya:
            continue
        left = page[ya:yb, max(0, x0 - STUB_SIDE_PROBE):max(1, x0)]
        right = page[ya:yb, min(W - 1, x1):min(W, x1 + STUB_SIDE_PROBE)]
        lo = float((left < BINARY_THRESHOLD_PATCH).mean()) if left.size else 0.0
        ro = float((right < BINARY_THRESHOLD_PATCH).mean()) if right.size else 0.0
        if max(lo, ro) >= STUB_SIDE_INK:
            hits.append(k)
    if not hits:
        return patch
    out = patch.copy()
    for k in hits:
        out[lab == k] = 255
    return out


# ── 侧边界行残余剥离（2026-08-25，用户 r7 实审：「还是有很多侧面
# 边框误入」）──────────────────────────────────────────────
# 图块条带按 cell_left_x/cell_right_x 裁（贴界行内缘），界行磨损断裂
# 时那道墙检不出来，条带就一路扩到列格名义边界、把界行圈进来——实测
# vol02/115、vol02/171 整列整列地在图块右缘留一条竖线。
#
# 判据同样搬到**图块之外**：看这条竖条落在哪儿。文字带（left_x~right_x）
# 是「正常居中字」的范围，界行按定义在带外的留白里；而字自己的竖笔
# （忄的左竖、阝、川、而 的边竖）无论多细都在带内。实测本批 71 个
# 「细高贴边」候选：完全落在文字带外的 33 个里 28 个是用户判错的格、
# 0 个落在用户判对的格；带内的 34 个里有 10 个是别的毛病、还有 1 个
# 正是「訓」的川字最右竖——只按形状剥必砍字。
#
# 红线不变：只剥与字身**不连通**的连通体（主连通体永不参与）。
# 「出文字带」本身还不够：带外也住着东西——职名列贴界行写的「臣」、
# 双行夹注宽过文字带的左子列。它们的外沿竖笔同样细高、同样在带外。
# 所以再加一条：竖条**近旁不许有别的墨块**。界行与字之间总隔着一段
# 留白（本批实测最近的字身也在 17px 之外）；而字的外沿竖笔身后紧挨着
# 这个字剩下的部分（隔几个像素）。
#
# 判「近旁」不能判「中间有没有」：字常常伸出文字带（「作」的右竖、
# 「人」的捺、「朱」「公」的末笔都越界），按「中间有墨就不动」会把这
# 一类的界行全放过——首版实测 25 条正样本里放过 5 条。
SIDE_RULE_MAX_W = 12       # 竖条宽度上限（px）——界行本来就细
SIDE_RULE_NEAR = 12        # 竖条内侧这么近还有别的墨块 → 那是字的一部分，不动

# ── 右缘穿边救援（2026-08-26 用户 r10：「有的整列从右边被剪切」）──
# 字写得压着界行时，cell_right_x 贴界行内缘裁，捺脚/横尾被齐刷刷切断
# （vol02/168 一页 5 列、vol02/176「大」的捺、vol02/119「之」的捺）。
# 裁条带前检测**穿过右裁切边的笔画组件**（从格内深处一直连到边外、
# 高 ≤30px——界行是长竖、噪点跨不过 10px 宽的检测窗），有就把 sx1
# 外扩到组件尽头。带进来的界行残段由 strip_side_rule / _assign_column
# 的竖线过滤收拾——它们已有独立回归（side-rule 分片）。
RIGHT_RESCUE_MAX = 12      # 右缘外扩上限（px）
LEFT_RESCUE_MAX = 12       # 左缘外扩上限（px）
# 【负结果·勿重造】「碎裂闸」——按图块内碎块统计判「一地碎渣不是字」，
# 2026-08-26 试过并**撤掉**。起因是 vol02/3 col1 底下一枚淡灰藏书印被
# 二值化炸成椒盐，切成 5 个假字格。用 255 个干净字定标出的阈值
# （小块<60px 计数 ≥8 且前 3 大连通体占墨 ≤0.80）在整册一放，除本页外
# 另中 18 格，逐格放大**全是真字**（書內跛勞說補寶臺觀讀圖…）——笔画多
# 的字本来就碎块多，这个统计量量的是**字繁不繁**，不是墨烂不烂。
# 后续又量过笔画性（最长横/竖游程、开运算存活率、墨密度、笔宽），
# 印区与真字**全部交叠**：印区 max(hrun,vrun) 0.25~0.67，真字 0.16~0.90。
# 二值图上分不开的根因是灰度已丢：真墨近黑、印是中灰，`output/*.png`
# 只有 0/255 两个值。要治得回到 s6 之前拿灰度做（印区局部对比度极低）。
# 收益侧也不支持：全册正文这一类只有这 5 格（~0.003%），远低于误伤
# 18 个真字的代价。真要做，先修灰度通道，别再在二值图上试统计闸。
SLIVER_W_RATIO = 0.12      # 裁紧后宽度低于此比例 × 列宽 → 疑似界行残条
SLIVER_ASPECT = 3.0        # ……且高 ≥ 此倍宽度（细长）才判，扁字不受影响
RIGHT_RESCUE_H = 30        # 穿边组件高度上限（超过是界行）
RIGHT_RESCUE_AREA = 25     # 穿边组件面积下限（噪点）
RIGHT_RESCUE_IN = 6        # 组件须从裁切边内这么深处伸出来（px）
RIGHT_RESCUE_OUT = 4       # 且越出裁切边这么多（px）
SIDE_RULE_ASPECT = 2.0     # 高/宽下限：得是「竖」的
SIDE_RULE_MIN_AREA = 40    # 墨量下限，纸面碎点交给别的闸


def widen_right_for_crossing(page_img: np.ndarray, sx0: int, sx1: int,
                             sy0: int, sy1: int) -> int:
    """穿边笔画检测 → 返回外扩后的 sx1（无穿边则原样返回）。"""
    img_w = page_img.shape[1]
    if sx1 + RIGHT_RESCUE_OUT >= img_w:
        return sx1                      # 已到页缘，无处可扩
    a = max(0, sx1 - 40)
    b = min(img_w, sx1 + RIGHT_RESCUE_MAX + 2)
    zone = (page_img[sy0:sy1, a:b] < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    fence = sx1 - a
    n, _lab, st, _c = cv2.connectedComponentsWithStats(zone, 8)
    far = sx1
    for k in range(1, n):
        x, _y, w, h, area = st[k]
        if h > RIGHT_RESCUE_H or area < RIGHT_RESCUE_AREA:
            continue
        if x <= fence - RIGHT_RESCUE_IN and x + w >= fence + RIGHT_RESCUE_OUT:
            far = max(far, a + int(x + w) + 1)
    return min(far, sx1 + RIGHT_RESCUE_MAX, img_w)


LEFT_RESCUE_W = 45         # 左缘穿边组件宽度上限：横向栏线/中缝线也会
                           # 细着穿过左裁切边（h≤30 挡不住），但它们
                           # 横贯整列（宽 ≫ 撇尖的 20~50px）且另一头
                           # 伸出探测窗外。全书抽样：真撇尖 w≤45。


def widen_left_for_crossing(page_img: np.ndarray, sx0: int, sx1: int,
                            sy0: int, sy1: int) -> int:
    """左缘镜像：撇尖/横尾穿过左裁切边 → 返回外扩后的 sx0。

    与右缘同判据（穿边 ≥4px、连进格内 ≥6px、高 ≤30），另加两道
    横条防线：宽 ≤LEFT_RESCUE_W，且不贴探测窗左缘（贴边=另一头在
    窗外，是横贯的栏线不是笔尖——首版全书扫出 324 点，一半是栏线）。"""
    if sx0 - RIGHT_RESCUE_OUT <= 0:
        return sx0                      # 已到页缘
    a = max(0, sx0 - LEFT_RESCUE_MAX - 2)
    b = min(page_img.shape[1], sx0 + 40)
    zone = (page_img[sy0:sy1, a:b] < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    fence = sx0 - a
    n, _lab, st, _c = cv2.connectedComponentsWithStats(zone, 8)
    near = sx0
    for k in range(1, n):
        x, _y, w, h, area = st[k]
        if (h > RIGHT_RESCUE_H or area < RIGHT_RESCUE_AREA
                or w > LEFT_RESCUE_W or x <= 0):
            continue
        if x <= fence - RIGHT_RESCUE_OUT and x + w >= fence + RIGHT_RESCUE_IN:
            near = min(near, a + int(x) - 1)
    return max(near, sx0 - LEFT_RESCUE_MAX, 0)


def strip_side_rule(patch: np.ndarray, x0: float,
                    text_x0: float, text_x1: float) -> np.ndarray:
    """剥掉图块左右缘吃进来的界行竖条（判据见上方注释）。

    x0 是图块左缘在整页上的 x，text_x0/text_x1 是本列**文字带**的左右界。
    """
    if patch.size == 0 or not np.isfinite([x0, text_x0, text_x1]).all():
        return patch
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return patch
    main = int(np.argmax(st[1:, 4])) + 1
    cand: list[tuple[int, int, int, bool]] = []      # (k, cx, cx+cw, 左侧?)
    for k in range(1, n):
        if k == main:
            continue
        cx, cw, ch, area = (int(st[k, 0]), int(st[k, 2]),
                            int(st[k, 3]), int(st[k, 4]))
        if area < SIDE_RULE_MIN_AREA or cw > SIDE_RULE_MAX_W:
            continue
        if ch < cw * SIDE_RULE_ASPECT:
            continue
        # 「中心出带」而不是「整条出带」：最外一列挨着的版框线常常正好
        # 压在文字带边上（实测 vol02/171 col1 的框线 1653~1660、带边
        # 1653.7，差 0.7px），按整条判会全数漏掉——本批因此从 17 个
        # 判错格涨到 21 个，误伤的判对格仍是 0。
        gc = x0 + cx + cw / 2.0
        if gc < text_x0:                              # 竖条中心在文字带左外
            cand.append((k, cx, cx + cw, True))
        elif gc > text_x1:                            # ……或右外
            cand.append((k, cx, cx + cw, False))
    if not cand:
        return patch
    # 近旁的墨块只数**字料**：够大，而且**两个方向都不细**
    # （w 和 h 都 > SIDE_RULE_MAX_W）。线状的东西一律不算近旁墨块——
    # 竖的是界行自己（同一条线常断成好几段，细高的成了候选、矮胖的没成，
    # 若互相算挡路则谁也剥不掉），横的是版框拐角那截横线（实测 24×9，
    # 又宽又矮，照样会把紧挨着的竖线挡下来）。字料在两个方向上都有厚度。
    others = [(int(st[k, 0]), int(st[k, 0]) + int(st[k, 2]))
              for k in range(1, n)
              if int(st[k, 4]) >= SIDE_RULE_MIN_AREA
              and int(st[k, 2]) > SIDE_RULE_MAX_W
              and int(st[k, 3]) > SIDE_RULE_MAX_W]
    hits = []
    for k, cx0_, cx1_, is_left in cand:
        near = any((ox0 - cx1_ if ox0 >= cx1_ else
                    (cx0_ - ox1 if ox1 <= cx0_ else -1)) < SIDE_RULE_NEAR
                   for ox0, ox1 in others)
        if near:
            continue                                  # 紧挨着字，那是字的笔画
        hits.append(k)
    if not hits:
        return patch
    out = patch.copy()
    for k in hits:
        out[lab == k] = 255
    return out


# ── 列端曲线切边（2026-08-25，用户定：图块的边不必是直线）────
# 用户看过框渣剥离的结果后提的：
#
#   最好还是做成一步……让最后这一个字它就不是一个方框，它可能是一个
#   曲线或弧线的一个边框，这样在截这个方框时，它的最下边这个边就直接
#   不要去取到它的下边框。
#
# 于是列端格的边不再是直线，而是一条**紧贴字身外沿、绕开版框**的路径
# （复用曲线切分那轮的 `_min_ink_path` DP 寻径）：路径以外的像素抹白，
# 等效于给图块切了一条弧线边。比矩形剥离强在能绕开**侧下方**的框线
# 断段——那些与字身垂直位置重叠，矩形判据够不着。
#
# 红线（用户定，写死成硬约束）：路径每一列都必须在该列**字身墨的最低
# 点之下**，所以字一个像素都切不到，连「从字内部空隙穿过去」这种绕法
# 都被禁掉。字身含字底部件——判据是 **bbox 垂直间隙**（实测「黙」的
# 四点底间隙 -5~-2px，与字身垂直重叠；框渣在字身之下，间隙 +2~+28px）。
# 用形态学膨胀不行：灬的点与最近笔画的像素距离远大于其 bbox 间隙，
# 首版用膨胀把「黙」的灬整个抹掉了。
CARVE_ZONE = 0.5           # 路径活动带（× 图块高，自底向上）
CARVE_NEAR_GAP = 1         # bbox 垂直间隙 < 此值的连通体并入字身受保护
CARVE_DEBRIS_H = 10        # 可切连通体的高度上限（px）——版框线本来就薄
CARVE_DEBRIS_AREA = 200    # 可切连通体的墨量上限（px）
CARVE_MARGIN = 2           # 路径与字身下沿的余量（px）
CARVE_KEEP_AREA = 60       # 字身外实体墨块并入保护的面积下限（px）
CARVE_KEEP_D = 15          # ……且离被切端至少这么远（框渣都贴着端行）
CARVE_STEP = 3             # 路径每列允许的纵向浮动（px）
CARVE_CHAR = 400.0         # 禁区（字身及其上方）的代价
CARVE_DEBRIS = 1.0         # 可穿墨（框渣）的代价
CARVE_LIFT = 0.35          # 「尽量贴字身」的偏好，把路径压到字身下沿


def _char_body(binary: np.ndarray) -> np.ndarray | None:
    """字身 + 字底部件的掩膜（判据见 CARVE_* 上方注释）。

    间隙量的是「候选块与**它头顶那片字料**的距离」，不是「与主连通体
    bbox 的距离」。后者在主连通体又高又瘦时形同虚设：「院」的阝几乎贯穿
    整块图块，页底那两条框线残段的 y 区间落在它的 bbox 里，算出来的
    间隙是 −96，于是被当字身保护、曲刀一刀也切不动（2026-08-25 用户
    指出列尾格是密集失败点，逐格看图查到这一条）。
    """
    n, lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return None
    main = int(np.argmax(st[1:, 4])) + 1
    # 第一遍按形状挑候选：又薄又小的才可能是框渣（「覽」下面那两条腿
    # h=27~61、面积 400~870，这一关就把它们挡在外面）
    cand = [k for k in range(1, n)
            if k != main
            and int(st[k, 3]) <= CARVE_DEBRIS_H
            and int(st[k, 4]) <= CARVE_DEBRIS_AREA]
    out = np.zeros(binary.shape, dtype=bool)
    for k in range(1, n):
        if k not in cand:
            out |= (lab == k)          # 字料：主连通体 + 一切不薄不小的块
    core = out.copy()
    h = binary.shape[0]
    ys = np.arange(h)[:, None]
    for k in cand:
        x, y, cw = int(st[k, 0]), int(st[k, 1]), int(st[k, 2])
        band = core[:y, x:x + cw]      # 候选块头顶、同一批列上的字料
        above = -1
        if band.size and band.any():
            rows = np.where(band, ys[:y], -1).max()
            above = int(rows)
        if y - above < CARVE_NEAR_GAP:  # 紧贴字料 → 是字的一部分，保护
            out |= (lab == k)
    return out


def carve_end_edge(patch: np.ndarray, bottom: bool = True) -> np.ndarray:
    """列端图块的曲线边：沿紧贴字身外沿、绕开版框的路径切，路径外抹白。

    bottom=True 切下边（列末格），False 切上边（列首格，上下翻转同解）。
    """
    work = patch if bottom else patch[::-1]
    binary = (work < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    h, w = binary.shape
    if h < 8 or not binary.any():
        return patch
    body = _char_body(binary)
    if body is None:
        return patch
    # 字身外的**实体墨块**也划进保护圈：左/右缘救回的断墨笔尖（「南」
    # 顶横的左端，111px、离端 24px）与主体不连通，_char_body 罩不住，
    # 寻径会从它旁边绕过去把它抹掉——left-cut 闸抓出的第 4 个对冲点
    # （前三个：曲线掩膜、横条取证窗、边缘噪点门槛）。版框渣不会被
    # 误保：版框带内缘钉桩后，框渣贴着被切的那一端（<CARVE_KEEP_D）。
    n_cc, lab_cc, st_cc, _ = cv2.connectedComponentsWithStats(binary, 8)
    for k in range(1, n_cc):
        if (st_cc[k, 4] >= CARVE_KEEP_AREA
                and st_cc[k, 1] + st_cc[k, 3] <= h - CARVE_KEEP_D):
            body = body | (lab_cc == k)
    ys = np.arange(h)[:, None]
    has = body.any(axis=0)
    bot = np.where(has, np.where(body, ys, -1).max(axis=0), -1)
    limit = np.where(has, bot + CARVE_MARGIN, 0)     # 路径在各列的上限
    lo = int(min(h * (1 - CARVE_ZONE), max(0, int(limit.min()))))
    rows = np.arange(lo, h, dtype=np.float64)
    band_ink = (work[lo:h] < BINARY_THRESHOLD_PATCH)
    forbid = rows[:, None] < limit[None, :]
    cost = (np.where(forbid, CARVE_CHAR, 0.0)
            + np.where(band_ink & ~forbid, CARVE_DEBRIS, 0.0)
            + CARVE_LIFT * (rows - lo)[:, None] / max(1, h - lo))
    path = np.maximum(_min_ink_path(cost, step=CARVE_STEP) + lo, limit)
    out = work.copy()
    for x in range(w):
        out[path[x]:, x] = 255
    return out if bottom else out[::-1]


# ── 列端渣格闸（2026-08-24 自评回流）─────────────────────
# 240 格分层自评里 39 个失败有 30 个是同一形态：列首/列尾多出一格，
# 落在版框横条区，掩蔽剥掉条身后剩下贴满两墙的矮横渣/碎点，被当字
# 输出（几乎全在 idx 末端，tail 层 48 格里 18 个）。判据在**格框图块**
# （裁紧前、清理后）上算。危险邻例是列尾的扁字（实测「二」：两笔各高
# ~18px 但只占 0.78 墙距、两笔纵向跨度≈整格），故「字证据」看两条：
# 非满宽连通体的纵向总跨度，或单个够高的连通体。
TAIL_JUNK_W2W = 0.92       # 连通体宽 ≥ 此比例 × 墙距 → 满宽条渣（字笔画到
                           #   文字带就停，条痕物理上穿墙，裁到图块边）
TAIL_JUNK_W2W_H = 0.35     # 满宽体高 ≥ 此比例 × 格高 → 不是条渣是「字粘条」
                           #   （字与条连成一个连通体时整体满宽；实测纯条渣
                           #   高 ≤0.26 格，字粘条 ≥0.6 格）
TAIL_JUNK_MIN_INK = 60     # 字证据连通体的最小墨量（px），滤碎点
TAIL_JUNK_CC_H = 0.30      # 单连通体高 ≥ 此比例 × 格高 → 直接是字
TAIL_JUNK_SPAN = 0.35      # 字证据连通体纵向总跨度 ≥ 此比例 × 格高 → 字
TAIL_JUNK_ONE_INK = 1000   # 孤「一」逃生口：单连通体墨量下限（实测条渣
TAIL_JUNK_ONE_W = 0.45     #   非满宽块 ≤725）、宽度下限（× 墙距）
TAIL_JUNK_ONE_H = 0.13     #   与高度下限（× 格高）


def is_end_cell_junk(patch: np.ndarray, cell_h: float) -> bool:
    """列首/列尾格：清理后只剩条痕残渣（非字）则 True。只应对端格调用。"""
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    if not binary.any():
        return True
    W = patch.shape[1]
    n, _lab, st, _ = cv2.connectedComponentsWithStats(binary, 8)
    top, bot = None, None
    for k in range(1, n):
        x, y, w, h, area = (int(st[k, 0]), int(st[k, 1]), int(st[k, 2]),
                            int(st[k, 3]), int(st[k, 4]))
        if w >= TAIL_JUNK_W2W * W and h < TAIL_JUNK_W2W_H * cell_h:
            continue                      # 满宽且矮：条渣，不算字证据
        if area < TAIL_JUNK_MIN_INK or h < 4:
            continue                      # 碎点
        if h >= TAIL_JUNK_CC_H * cell_h:
            return False                  # 够高，直接是字
        if (area >= TAIL_JUNK_ONE_INK and w >= TAIL_JUNK_ONE_W * W
                and h >= TAIL_JUNK_ONE_H * cell_h):
            return False                  # 孤「一」：矮但宽厚墨足
        top = y if top is None else min(top, y)
        bot = y + h if bot is None else max(bot, y + h)
    if top is not None and (bot - top) >= TAIL_JUNK_SPAN * cell_h:
        return False                      # 「二/三」类：多笔跨度撑起整格
    return True


HEAD_CELL_MIN_H = 0.5      # 抬头位的字必须有这么高的连通体（× 格高）


def is_head_cell_junk(patch: np.ndarray, cell_h: float) -> bool:
    """抬头位的格：没有整字级的连通体就判空。

    抬头行是页级补出来的（补一行则全部列都多一格），但**抬头只发生在
    个别列**——普通列的抬头位本来就是空的，落在那儿的墨几乎都是版框
    横线。通用的列端渣格闸对这里太松：两条框线只要在某处相连，bbox
    就是「满宽 + 0.75 格高」，被当成「字粘条」放行（实测 vol01/33:9:0）。
    抬头位的判据因此收紧成：最大连通体高 < HEAD_CELL_MIN_H 格 → 判空。
    真抬头字是整字，一定够高；框线组合再怎么相连也矮。
    """
    binary = (patch < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    if not binary.any():
        return True
    n, _lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return True
    for k in range(1, n):
        h = int(st[k, 3])
        w = int(st[k, 2])
        area = int(st[k, 4])
        if h < HEAD_CELL_MIN_H * cell_h or area < TAIL_JUNK_MIN_INK:
            continue
        # 满宽且填充稀疏 = 上下两条框线在某处相连，不是字
        if w >= TAIL_JUNK_W2W * patch.shape[1] \
                and area < 0.30 * w * h:
            continue
        return False
    return True


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
                              # ——只对**边缘带**生效（条带左右缘 ±10px、
                              # 格界线 ±SPECKLE_ZONE）。文字区内用下面的
                              # 绝对小阈值：断版会把字里的短横断成小块，
                              # 0.004 一刀切会把它们当噪点吃掉
                              # （2026-08-26 用户 r10：「图像处理似乎删去
                              # 了文字中的短横……文字区域阈值特别小，
                              # 边缘部分阈值可稍大」）。
MIN_COMP_AREA_INTERIOR = 12   # 文字区内的噪点阈值（px，几乎不删）
INTERIOR_X_MARGIN = 10        # 离条带左右缘超过此才算文字区（px）
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

# ── 曲线切分原型（P2 #12，2026-08-25 调查轮，默认关）──────────
# _split_touching 的水平直线刀升级为「最小墨量路径」：在格线 ±SPLIT_WIN
# 带内做 DP 寻径（从左到右、每步纵向浮动 ±SPLIT_CURVE_STEP px），沿总墨
# 量最小的路径断开连通体。两处收益（vol01 全册实测见
# .claude/doc/split_curve_boundary_research.md 任务B）：
# 直刀会在颈部整行清墨、切断斜穿该行的真笔画；曲刀绕着笔画走，只在
# 真正的字间缝隙处过刀。开关默认关——量产启用前需按金标漂移协议重核。
SPLIT_CURVE = False        # True 时 _assign_column 改用 _split_touching_curve
SPLIT_CURVE_STEP = 1       # 路径每列允许的纵向浮动（px/步）
SPLIT_CURVE_EPS = 0.02     # 距格线偏离的微小代价（px⁻¹），墨量相同时贴格线走
# 碎片粘连修正：连通体在格线上方的部分不足 MIN_PIECE×格高时（例如上一字
# 只有一条撇尾混进来、其主体是独立连通体——vol01/22 col9「修/集」病灶），
# 「上半块 ≥MIN_PIECE」以连通体顶来量就是无意义的（上半块本来就不是整字，
# 它要与上格已有的字身合并）。此时改用窄带 g±SPLIT_FRAG_WIN×格高准切，
# 不再卡 MIN_PIECE——窄带同时守住「草的艹被切走」老病灶（那道错缝在
# g+0.3 格高，够不着窄带）。
SPLIT_FRAG_WIN = 0.07      # 碎片粘连时的准切窄带（× 格高）
SPLIT_CURVE_BUDGET = 0.5   # 曲刀墨预算 = 此系数×NECK_ABS×列宽（比直刀紧）


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
            # 碎片粘连（vol01/22「修/集」病灶）：连通体在格线上方的延伸
            # 装不下一个完整上字——组件里只有上一字的残尾（其主体是独立
            # 连通体）。此时「上半块 ≥MIN_PIECE」以组件顶来量毫无意义，
            # 反而把刀强行压进下一字（全书同型 41 处不切 + 29 处刀位
            # 偏移）。豁免 MIN_PIECE，改在 g±SPLIT_FRAG_WIN 窄带内准切
            # ——窄带同时守住「草的艹被切走」老病灶（那道错缝在
            # g+0.3 格高，够不着窄带）。
            frag = (g - y) < MIN_PIECE * cell_h
            w_here = SPLIT_FRAG_WIN * cell_h if frag else win
            lo = int(max(y + (0.0 if frag else 0.2 * cell_h), g - w_here))
            hi = int(min(y + ch - 0.2 * cell_h, g + w_here,
                         y + (ch if frag else FIT_RATIO * cell_h)))
            if hi <= lo:
                continue
            thin = np.flatnonzero(prof[lo:hi] <= NECK_ABS * col_w) + lo
            # 上半块必须够得上一个字。否则会切在「粘着的上一字残尾」和
            # 本字之间——那道缝也在格线附近、也很细，切下去本字就少一个
            # 部首（实测把「草」的艹切给了上一格）。碎片粘连时该约束
            # 失效（见上），只留下半块防碎渣。
            if not frag:
                thin = thin[thin - y >= MIN_PIECE * cell_h]
            thin = thin[y + ch - thin >= MIN_TAIL * cell_h]
            if thin.size == 0:
                continue
            # 取细颈里**离格线最近**的一行，而不是最细的一行。上一字的
            # 竖尾是一根长而匀的细杆，整段都一样细，压根没有「局部谷底」；
            # 按最细取会跑到杆子末端去切，切完上半块还是两个字。
            r = int(thin[np.argmin(np.abs(thin - g))])
            out[r:r + 2][comp[r:r + 2]] = 0    # 切两行，断开 8 连通
    return out


def _min_ink_path(cost: np.ndarray, step: int = SPLIT_CURVE_STEP) -> np.ndarray:
    """带状代价图上的最小代价横穿路径（DP）。

    cost: (B, W) 非负代价。返回长度 W 的行号数组 path，
    满足 |path[x+1] - path[x]| ≤ step，且 Σ cost[path[x], x] 最小。
    """
    B, W = cost.shape
    dp = cost[:, 0].astype(np.float64).copy()
    back = np.zeros((B, W), dtype=np.int16)
    idx = np.arange(B)
    for x in range(1, W):
        # cand[k] = dp 在 y+off 处的值（off ∈ [-step, step]）
        best = np.full(B, np.inf)
        arg = np.zeros(B, dtype=np.int16)
        for off in range(-step, step + 1):
            src = idx + off
            ok = (src >= 0) & (src < B)
            v = np.full(B, np.inf)
            v[ok] = dp[src[ok]]
            upd = v < best
            best[upd] = v[upd]
            arg[upd] = off
        dp = best + cost[:, x]
        back[:, x] = arg
    path = np.empty(W, dtype=np.int32)
    path[-1] = int(np.argmin(dp))
    for x in range(W - 1, 0, -1):
        path[x - 1] = path[x] + back[path[x], x]
    return path


def _split_touching_curve(binary: np.ndarray,
                          cells: list[tuple[int, float, float]],
                          cell_h: float, col_w: float) -> np.ndarray:
    """曲线版 _split_touching：颈部改沿**最小墨量路径**下刀（原型，默认关）。

    与直线版的三点差异：

    1. 刀口不是水平行，而是格线 ±SPLIT_WIN 带内 DP 找出的最小墨量路径
       （每步纵向浮动 ±SPLIT_CURVE_STEP px）——直刀在颈部整行清墨，会把
       斜穿该行的真笔画（撇/捺/斜钩）切出一个平口；曲刀绕开笔画，只在
       字间缝隙里走；
    2. 「颈够细」的判据从「存在一行墨宽 ≤NECK_ABS×列宽」换成等价的
       「路径总穿墨 ≤NECK_ABS×列宽」——路径能绕，同样的墨预算能对付
       更歪斜的粘连；
    3. 碎片粘连修正（见 SPLIT_FRAG_WIN 注释）：连通体在格线上方不足
       MIN_PIECE×格高时不再按连通体顶卡 MIN_PIECE（上半块本来就只是
       上一字的零件），改在 g±SPLIT_FRAG_WIN 窄带内准切。

    路径两行清墨（断开 8 连通），只清本连通体的像素，不碰邻组件。
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    out = binary.copy()
    lines = [top for _i, top, _b in cells[1:]]
    win = SPLIT_WIN * cell_h
    H, W = binary.shape
    for k in range(1, n):
        x, y, cw, ch, _area = stats[k]
        if ch <= SPLIT_H_RATIO * cell_h:
            continue
        comp = labels == k
        for g in lines:
            if not (y < g < y + ch):
                continue
            frag = (g - y) < MIN_PIECE * cell_h      # 上方只是上一字碎片
            w_here = SPLIT_FRAG_WIN * cell_h if frag else win
            lo = int(max(y + (0.0 if frag else 0.2 * cell_h), g - w_here))
            hi = int(min(y + ch - 0.2 * cell_h, g + w_here,
                         y + FIT_RATIO * cell_h))
            if frag:
                hi = int(min(y + ch - 0.2 * cell_h, g + w_here))
            lo = max(0, lo)
            hi = min(H - 1, hi)
            if hi <= lo:
                continue
            band = comp[lo:hi].astype(np.float64)
            # 贴格线偏好：墨量相同时选离格线近的路径
            rows = np.arange(lo, hi, dtype=np.float64)
            band = band + SPLIT_CURVE_EPS * np.abs(rows - g)[:, None] / cell_h
            path = _min_ink_path(band)
            pierced = int(comp[path + lo, np.arange(W)].sum())
            # 曲刀预算比直刀紧一半：好缝实测穿墨仅 1~20px，收紧只挡
            # 坏刀——防止在重度磨损页的噪糊粘连里硬穿割断真笔画
            # （调查报告任务B风险项，reg_167_9_277）
            if pierced > SPLIT_CURVE_BUDGET * NECK_ABS * col_w:
                continue                              # 颈太厚，留给硬切
            r_rows = path + lo
            r_mean = float(r_rows.mean())
            if not frag:
                if r_mean - y < MIN_PIECE * cell_h:
                    continue
                if y + ch - r_mean < MIN_TAIL * cell_h:
                    continue
            else:
                if y + ch - r_mean < MIN_TAIL * cell_h:
                    continue
            xs = np.arange(W)
            for dy in (0, 1):
                rr = np.clip(r_rows + dy, 0, H - 1)
                sel = comp[rr, xs]
                out[rr[sel], xs[sel]] = 0
    return out


def _assign_column(col_gray: np.ndarray,
                   cells: list[tuple[int, float, float]],
                   cell_h: float, col_w: float,
                   left_ext: int = 0, right_ext: int = 0
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
    _splitter = _split_touching_curve if SPLIT_CURVE else _split_touching
    # 去线、未拆的图另留一份：步骤 3 的「拆分前连通」证据从这上面取
    prelim = _strip_lines(_column_binary(col_gray), cell_h)
    binary = _splitter(prelim, cells, cell_h, col_w)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    _n_raw, raw_lab = cv2.connectedComponents(prelim, 8)
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
    lines_y = sorted({t for _i, t, _b in cells} | {b for _i, _t, b in cells})

    def _near_line(cy: float) -> bool:
        return any(abs(cy - ly) <= SPECKLE_ZONE for ly in lines_y)

    strip_w = binary.shape[1]
    for k in range(1, n):
        x, y, cw, ch, area = stats[k]
        interior = (x > INTERIOR_X_MARGIN
                    and x + cw < strip_w - INTERIOR_X_MARGIN
                    and not _near_line(y + ch / 2.0))
        # 左右缘救援带里的**穿边**碎片是刚救回来的笔尖（「南」顶横的
        # 左端断墨成 60px 小块），不能再按边缘噪点门槛（79px）吃掉——
        # 从救援带一直伸进原裁切边内的，按文字区门槛保。整体缩在带内
        # 的照旧当渣（点渣清理已处理大半，这里兜漏网的）。
        rescued = ((left_ext > 0 and x < left_ext
                    and x + cw >= left_ext + 4)
                   or (right_ext > 0 and x + cw > strip_w - right_ext
                       and x <= strip_w - right_ext - 4))
        if area < (MIN_COMP_AREA_INTERIOR if (interior or rescued)
                   else min_area):
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

    # ── 跨格重占检查（用户实审反馈：连通片整块被错删）────────
    # 字身与边缘残渣/邻字连成一体后，若整体认给某一格，clean_patch 会把
    # 它从其他格的图块里整片抹掉——实测 vol02 全书 3.5k 格核心区被删
    # ≥250px 墨，93% 出自本路径。判据：连通体在**归属格之外**某格的
    # **中央带**（30%~70% 格高）里有实质墨，说明那格的字身（的一部分）
    # 在这个连通体里，谁都不许整体独占 → 降级为粘连块按格界硬切，
    # 各归各格。中央带是关键余量：「守」的宀、出头笔画都住在邻格的
    # **边缘带**，不会触发（不然会回退到「守削成寸」的老病）。
    CORE_BAND = 0.30
    # 110：r10 实审 vol01/6 1:13「爲」——爪头与上字连成一体（h 不足
    # MERGE_H，拆颈不管），整块认给上字，爲头被吃。它在本格中央带的墨
    # 是 123px，原阈值 200 放行。中央带口径本身已挡住「守」的宀类
    # 误伤（那些住边缘带，中央带墨 ≈0），阈值只防噪点，压到 110。
    CORE_SPLIT_MIN = 110
    _rowcache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def _rows_of(k: int) -> tuple[np.ndarray, np.ndarray]:
        if k not in _rowcache:
            ys = np.nonzero(labels == k)[0]
            _rowcache[k] = np.unique(ys, return_counts=True)
        return _rowcache[k]

    def overclaims(k: int, own_cell: int) -> bool:
        rows, cnt = _rows_of(k)
        for i, top, bot in cells:
            if i == own_cell:
                continue
            bh = bot - top
            a, b = top + CORE_BAND * bh, bot - CORE_BAND * bh
            m = int(cnt[(rows >= a) & (rows < b)].sum())
            if m >= CORE_SPLIT_MIN:
                return True
        return False

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
        if overclaims(k, i):
            # 它占着别格的中央带：不能由 i 独占。只跳过**这个配对**——
            # 若那个「别格」正是它真正的字身格，后面的配对会把它认走；
            # 真正横跨多格中央带的（对谁都 overclaims）会一路配不上，
            # 落到第 3 步被硬切。（第一版在这里直接弹出 live 转硬切，
            # 结果它稍后仍被真身格 claim，bodies 循环 KeyError。）
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
    # 最强证据先行：**拆分前连通**。邻字压线的笔尾（捺脚/竖钩/顶横）被
    # _split_touching 或墨色断点从本体上切下来后，就成了贴着格线的零散
    # 部件——四级键的「越格量」这时必然判错：笔尾伸进哪格，并进那格的
    # 越格量就最小（r10 实审 vol01/8 与 /11 的 9:11，上/下邻字的笔尾都
    # 被判给了本格，用户手工裁掉）。而它在**去线未拆**的图上与真身原是
    # 一块墨。墨迹相连不是距离阈值（间隙分布重叠的教训还在），是物理
    # 证据：与**唯一**一个字身同源的部件直接归还；同源字身有两个以上
    # （真粘连对半拆开的场合）或一个也没有，才走四级键。
    # 只认**窄**部件（≤0.45 列宽）：拆颈拆下来的东西有两种，邻字伸过来
    # 的笔尾（捺脚/竖钩，实测 0.27 列宽）归还是对的；被上字竖尾粘住的
    # 下字**顶横**（0.7~0.9 列宽，test_split_touching_cuts_at_the_stem）
    # 是下字的部首，归还就把拆颈白拆了——宽部件是「字的横向笔画」，
    # 窄部件才是「伸过来的尾巴」。
    _rawcache: dict[int, int] = {}

    def _raw_of(k: int) -> int:
        if k not in _rawcache:
            x, y, cw, ch, _a = (live[k] if k in live else
                                tuple(int(v) for v in stats[k][:5]))
            win = labels[y:y + ch, x:x + cw] == k
            vals = raw_lab[y:y + ch, x:x + cw][win]
            _rawcache[k] = int(vals[0]) if vals.size else 0
        return _rawcache[k]

    raw_owner: dict[int, set[int]] = {}
    for kb, ib in claim.items():
        raw_owner.setdefault(_raw_of(kb), set()).add(ib)

    for k in live:
        if k in claim:
            continue
        x, y, cw, ch, _a = live[k]
        cx = x + cw / 2
        kin = (raw_owner.get(_raw_of(k))
               if cw <= 0.45 * col_w else None)
        if kin is not None and len(kin) == 1:
            best = next(iter(kin))
            if not overclaims(k, best):
                owner[labels == k] = best + 1
                add(best, x, y, x + cw, y + ch)
                continue
            merged.append(k)                          # 同源但占别格中央带
            continue
        best, best_key = None, None
        for i, (bx0, by0, bx1, by1) in bodies.items():
            top, bot = cell_span[i]
            # 字身自己已经越线的，越格量按「格线 ∪ 字身实占」量：字明摆着
            # 写长了/压线了，它伸过去的那段行区里的浮散笔画（r10 实审
            # vol01/11 9:11——下字的顶横浮在上格底带、正被下字身体盖着的
            # 行区里）并进来不该再记越格。字身没越线时与原口径完全一致，
            # 「守」的宀类判断不受影响。
            top, bot = min(top, by0), max(bot, by1)
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
        if overclaims(k, best):
            merged.append(k)                          # 占着别格中央带 → 硬切
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


# ── 版框带内缘钉桩（2026-08-25，用户「列尾格是密集失败点」）────────
# 列端格的格线是等分算出来的，撞上版框时会一路裁到框线上甚至框外。
# 框墨一旦进了条带就很难再拿掉：它常和字的竖笔**粘成一个连通体**
# （实测「院」的阝、「續」「蒐」的末笔都是），剥离只动独立连通体、
# 曲刀的红线又不许切与字身连通的墨，两条路都堵死。
#
# 所以把桩打在**进来之前**：条带的上下界先钉在版框带的内缘。
# 内缘的量法——从最外那条框线行往里走，**只要下一行还是「框线行」就
# 继续**（框线磨损会散成几行）。判「框线行」必须用 grid_segment 里那套
# 标定过的双档（行墨 ≥0.5，或行墨 ≥0.28 且最长横向连续段 ≥0.22 页宽），
# 不能只看行墨率：末行字的行墨能到 0.23~0.55，只看行墨会把整行字当成
# 框带吞掉（首版取 0.22，实测把 vol01/28 col8 的末字砍掉一半）。
# 再加两条保险：框带最厚 FRAME_BAND_MAX 行；钉桩最多吃掉端格的
# FRAME_BAND_MAX_CUT 比例，越过就不钉——宁可留框渣，绝不吞字。
FRAME_BAND_MAX = 25        # 框带最厚走这么多行
FRAME_BAND_MAX_CUT = 0.35  # 钉桩最多吃掉端格的这个比例（× 格高）


def frame_band_inner(page: np.ndarray) -> tuple[int, int]:
    """整页上下版框带的**内缘**行号 (top_inner, bot_inner)。检不出给页界。"""
    from .grid_segment import (BINARY_THRESHOLD, FRAME_ROW_T, FRAME_ROW_T2,
                               FRAME_RUN_T, measure_row_frames)
    if page.ndim == 3:
        page = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    h, w = page.shape[:2]
    ft, fb = measure_row_frames(page)
    binary = page < BINARY_THRESHOLD
    rowink = binary.sum(axis=1) / max(1, w)

    def is_bar(y: int) -> bool:
        if rowink[y] >= FRAME_ROW_T:
            return True
        if rowink[y] < FRAME_ROW_T2:
            return False
        row = binary[y].astype(np.int8)
        d = np.diff(np.concatenate(([0], row, [0])))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        run = int((ends - starts).max()) if starts.size else 0
        return run / max(1, w) >= FRAME_RUN_T

    top = 0
    if ft is not None:
        y = int(ft)
        while y + 1 < h and y - ft < FRAME_BAND_MAX and is_bar(y + 1):
            y += 1
        top = y + 1
    bot = h
    if fb is not None:
        y = int(fb)
        while y - 1 >= 0 and fb - y < FRAME_BAND_MAX and is_bar(y - 1):
            y -= 1
        bot = y
    return top, bot


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
        frame_in_top, frame_in_bot = frame_band_inner(page_img)
        n_head_rows = int((grid.get("grid") or {}).get("head_raise_rows") or 0)
        # 夹注跨度的尺子：列距（书级刚性常量）。老产物没有就退回图块宽度
        jz_ref_w = float((grid.get("grid") or {}).get("period") or 0.0) or None
        results: list[tuple[CharInstance, np.ndarray]] = []
        jz_replaced: set[str] = set()

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
            sy0_pre = int(round(max(0.0,
                min(float(c["y_top"]) for c in cells))))
            sy1_pre = int(round(min(float(img_h),
                max(float(c["y_bottom"]) for c in cells))))
            sx1_widened = widen_right_for_crossing(
                page_img, sx0, sx1, sy0_pre, sy1_pre)
            right_delta = sx1_widened - sx1
            sx1 = sx1_widened
            sx0_widened = widen_left_for_crossing(
                page_img, sx0, sx1, sy0_pre, sy1_pre)
            left_delta = sx0 - sx0_widened
            sx0 = sx0_widened
            pad_y = cell_h_ref * self.padding_ratio
            sy0 = int(round(max(0.0, min(float(c["y_top"]) for c in cells) - pad_y)))
            sy1 = int(round(min(float(img_h),
                               max(float(c["y_bottom"]) for c in cells) + pad_y)))
            # 版框带内缘钉桩：框墨不进条带（理由见 frame_band_inner 上方）。
            # 硬保险：最多吃掉端格的 FRAME_BAND_MAX_CUT，越过就不钉。
            cut_lim = cell_h_ref * FRAME_BAND_MAX_CUT
            if frame_in_top - sy0 <= cut_lim:
                sy0 = max(sy0, frame_in_top)
            if sy1 - frame_in_bot <= cut_lim:
                sy1 = min(sy1, frame_in_bot)
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            strip = page_img[sy0:sy1, sx0:sx1]
            if right_delta > 0 or left_delta > 0:
                # 外扩带进来的**非穿边**小组件只可能是界行点渣（磨损界行
                # 是一串点，恰好整体落在原裁切边外侧）——清掉；穿边的
                # 笔画（跨过原裁切边、连进格内）保留，这正是外扩的目的。
                # 左右两侧同一逻辑镜像。
                strip = strip.copy()
                fence0 = (sx1 - right_delta) - sx0
                bs = (strip < BINARY_THRESHOLD_PATCH).astype(np.uint8)
                nrc, lrc, strc, _ = cv2.connectedComponentsWithStats(bs, 8)
                for k in range(1, nrc):
                    if right_delta > 0 and strc[k, 0] >= fence0 - 1:
                        strip[lrc == k] = 255
                    elif (left_delta > 0
                          and strc[k, 0] + strc[k, 2] <= left_delta + 1):
                        strip[lrc == k] = 255
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
                    # 左右缘救援外扩了条带就同步放宽掩膜边界，别把刚救回
                    # 的笔尖又涂白（带进来的界行归下游剥离，不归这里）
                    ca = max(0, int(round(blx)) - sx0 - left_delta)
                    cb = min(strip.shape[1],
                             int(round(brx)) - sx0 + right_delta)
                    if ca > 0:
                        strip[ra:rb, :ca] = 255
                    if cb < strip.shape[1]:
                        strip[ra:rb, cb:] = 255

            col_entries: list[tuple[int, float | None, CharInstance]] = []
            local = [(int(c["index"]),
                      float(c["y_top"]) - sy0,
                      float(c["y_bottom"]) - sy0) for c in cells]
            strip = mask_frame_bars_outside(
                strip, local, int(round(left_x)) - sx0,
                int(round(right_x)) - sx0, cell_h_ref,
                right_ext=right_delta, left_ext=left_delta)
            if self.strategy == "component_owner":
                boxes, owner = _assign_column(strip, local, cell_h_ref,
                                              float(sx1 - sx0),
                                              left_ext=left_delta,
                                              right_ext=right_delta)
            else:
                boxes, owner = {}, None

            # 列端渣格闸的候选：首末各 2 格（渣有时占两格，闸从端头向内
            # 走，遇到第一格真字就停——见 is_end_cell_junk 上方注释）。
            order = [i for i, _t, _b in local]
            end_cand = set(order[:2 + n_head_rows] + order[-2:])
            # 曲线切边只碰**最外一格**：只有它挨着版框。列端渣格闸取
            # 首末各 2 格（渣有时占两格），但短列里那两个集合会重叠，
            # 拿它切边会把列首格**下方的邻字残余**也当框线切掉。
            head_cell = order[0] if order else None
            tail_cell = order[-1] if order else None
            end_patches: dict[int, tuple[np.ndarray, float]] = {}
            jz_pre: dict[int, tuple[np.ndarray, float, float]] = {}
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
                patch = strip_speckle_band(patch, ltop - y0, lbot - y0)
                # 侧边界行残余：全列都会中招，不限列端（用户 r7）
                patch = strip_side_rule(patch, float(sx0), left_x, right_x)
                # 列端格：剥掉与字身分离的版框碎渣（2026-08-25 用户定
                # 口径——框渣算可后处理的污染，不算错误截取）。自检
                # flags 与紧裁都在剥后的图块上算，口径统一为「去框后」。
                if idx in end_cand:
                    patch = strip_frame_debris(patch, ltop - y0,
                                               lbot - y0, cell_h)
                    # 框线断段：判据在图块之外（列外墨率），必须传整页
                    patch = strip_frame_stub(patch, page_img, int(sx0),
                                             int(sx1), int(sy0 + y0))
                    # 曲线切边：列末切下边、列首切上边（用户定——图块的
                    # 边不必是直线，绕开版框即可）。放在框渣剥离之后，
                    # 剥不掉的粘连/侧下方断段由它兜底。
                    if idx == tail_cell:
                        patch = carve_end_edge(patch, bottom=True)
                    if idx == head_cell:
                        patch = carve_end_edge(patch, bottom=False)

                x0 = float(sx0)
                x1 = float(sx1)
                py0 = float(sy0 + y0)
                py1 = float(sy0 + y1)

                ink = _patch_ink_ratio(patch)
                flags: list[str] = []
                if idx in end_cand:
                    end_patches[idx] = (patch.copy(), cell_h)
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

                # 夹注缝在**格框图块**上量（判据阈值按格框几何标定：单字
                # 只占 0.6~0.7 列宽是唯一不重叠的量，裁紧后谁都是满宽）
                jz_center = _jiazhu_gap_center(patch, jz_ref_w)
                # 每格都留住裁紧前图块与几何：桥接格（自己量不出缝、由
                # 邻格插值确认成夹注）拆 a/b 时也要用
                jz_pre[idx] = (patch.copy(), float(sx0), float(sy0 + y0))

                # 裁紧（2026-08-24 用户定版）：图块**完完全全包住本字墨迹**
                # ±TIGHT_MARGIN，左右不再留到墙的空白——贴墙的空白装的从来
                # 不是字，是边框/界行残渣。归属清理已把外人墨抹掉，剩下的
                # 墨迹外接框就是本字。自检 flags 全部在裁紧**前**的格框图块
                # 上算完（边缘带比例等阈值是按格框标定的）。判空格保持格框。
                ty, tx = np.nonzero(patch < BINARY_THRESHOLD_PATCH)
                if ty.size:
                    tx0 = max(0, int(tx.min()) - TIGHT_MARGIN)
                    tx1 = min(patch.shape[1], int(tx.max()) + 1 + TIGHT_MARGIN)
                    ty0 = max(0, int(ty.min()) - TIGHT_MARGIN)
                    ty1 = min(patch.shape[0], int(ty.max()) + 1 + TIGHT_MARGIN)
                    x0 = float(sx0 + tx0)
                    x1 = float(sx0 + tx1)
                    py1 = float(sy0 + y0 + ty1)
                    py0 = float(sy0 + y0 + ty0)
                    patch = patch[ty0:ty1, tx0:tx1]
                    ink = _patch_ink_ratio(patch)

                inst = CharInstance(
                    id=make_id(book, page, col_no, idx),
                    book=book, page=page, col=col_no, idx=idx,
                    bbox=(x0, py0, x1, py1),
                    cell_type="char",
                    ocr_text=cell.get("text") or None,
                    ocr_confidence=float(cell.get("confidence", 0.0)),
                    patch_path=f"patches/{page}/{col_no}_{idx}.png",
                    ink_ratio=round(ink, 4),
                    height=round(py1 - py0, 2),
                    width=round(x1 - x0, 2),
                    flags=flags,
                )
                results.append((inst, patch))
                col_entries.append((idx, jz_center, inst))
            # 细条闸（2026-08-26 自评 r2）：裁紧后**窄成一条**的格装不下
            # 任何字，是界行残条冒充字（实测 28 格全在列端，宽 4~20px、
            # 高 41~145，长宽比 5~18）。判据只用几何，不看位置——它不
            # 挑列端，哪儿冒出来都算。宽度阈值取 0.12 列距（≈21px）：
            # 真字最窄的「丨」类部件也有 0.15 列距以上，且必须同时细长
            # （高 ≥3 倍宽）才判，扁字（一/二，宽 0.6 列距）不受影响。
            for _i, _c, inst in col_entries:
                if inst.cell_type != "char":
                    continue
                bw = inst.bbox[2] - inst.bbox[0]
                bh = inst.bbox[3] - inst.bbox[1]
                if bw < SLIVER_W_RATIO * col_w and bh >= SLIVER_ASPECT * bw:
                    inst.cell_type = "empty"
                    if "sliver" not in inst.flags:
                        inst.flags.append("sliver")
            # 列端渣格闸：从两端向内走（各最多 2 格），渣格转 empty +
            # tail_junk 旗，遇到第一格真字停。判据在裁紧前的格框图块上算。
            by_idx = {i: inst for i, _c, inst in col_entries}
            for seq in (order[:2], order[::-1][:2]):
                for i in seq:
                    info, inst = end_patches.get(i), by_idx.get(i)
                    if info is None or inst is None:
                        break
                    if "tail_junk" in inst.flags:
                        continue
                    if not is_end_cell_junk(*info):
                        break
                    inst.cell_type = "empty"
                    inst.flags.append("tail_junk")
            # 抬头位（页级补出来的行）：只有个别列真有抬头字，其余列那
            # 一格本来就空，落在那儿的墨几乎都是版框横线。通用闸对这里
            # 太松（两条框线相连就冒充「字粘条」），另用严判据。
            for i in order[:n_head_rows]:
                info, inst = end_patches.get(i), by_idx.get(i)
                if info is None or inst is None or inst.cell_type != "char":
                    continue
                if is_head_cell_junk(*info):
                    inst.cell_type = "empty"
                    if "tail_junk" not in inst.flags:
                        inst.flags.append("tail_junk")
            # 夹注/双行小字：连续 ≥2 格、缝中心对齐才落 flag（疑似层）。
            # 下游把 jiazhu 图块隔离成单例，不进簇、不进训练。
            jz_runs = flag_jiazhu_runs([(i, c) for i, c, _ in col_entries])
            for j in jz_runs:
                for i, _c, inst in col_entries:
                    if i == j and "jiazhu" not in inst.flags:
                        inst.flags.append("jiazhu")
            # ── 段端收编：奇数字末行单字 / 漏拆的末行 ──────────
            jz_tail_a: set[int] = set()
            if jz_runs:
                for e in [i for i in sorted(jz_runs) if i + 1 not in jz_runs]:
                    t = e + 1
                    if t in jz_runs or t not in jz_pre:
                        continue
                    tinst = by_idx.get(t)
                    if tinst is None or tinst.cell_type != "char" \
                            or tinst.sub:
                        continue
                    pre_t = jz_pre[t][0]
                    cx = int(round(jz_runs[e]))
                    ys_t, xs_t = np.nonzero(pre_t < BINARY_THRESHOLD_PATCH)
                    if xs_t.size < JZ_TAIL_MIN_INK:
                        continue
                    frac_a = float((xs_t >= cx).mean())
                    in_band = int(((xs_t >= cx - JZ_TAIL_GAP_BAND)
                                   & (xs_t <= cx + JZ_TAIL_GAP_BAND)).sum())
                    a_xs = xs_t[xs_t >= cx]
                    b_xs = xs_t[xs_t < cx]
                    w_full = pre_t.shape[1]
                    a_narrow = bool(a_xs.size) and (
                        a_xs.max() - a_xs.min() + 1 <= JIAZHU_MASS_W * w_full)
                    # b 侧最大连通体：真笔画（「一」~700+）还是邻字残渣。
                    # **分型不能拿墨占比**——瘦字的墨占比跟残渣重叠。
                    b_cc = 0
                    if b_xs.size:
                        bh = (pre_t[:, :max(1, cx)]
                              < BINARY_THRESHOLD_PATCH).astype(np.uint8)
                        nb, _lb, stb, _cb = \
                            cv2.connectedComponentsWithStats(bh, 8)
                        if nb > 1:
                            b_cc = int(stb[1:, 4].max())
                    row_ok = (a_xs.size >= JZ_TAIL_MIN_INK
                              and b_xs.size >= JZ_TAIL_MIN_INK
                              and b_cc >= JZ_ROW_B_CC
                              and in_band <= JZ_TAIL_GAP_FRAC * xs_t.size
                              and a_narrow
                              and b_xs.max() - b_xs.min() + 1
                                  <= JIAZHU_MASS_W * w_full)
                    if row_ok:
                        # 漏拆行（末行两字，单格判据量不出缝）：正常拆 a/b
                        jz_runs[t] = float(jz_runs[e])
                        if "jiazhu" not in tinst.flags:
                            tinst.flags.append("jiazhu")
                    elif (frac_a >= JZ_TAIL_A_FRAC and a_narrow
                          and b_cc < JZ_ROW_B_CC):
                        # 单字尾（奇数字末行）：b 侧只有碎渣，只发 a 半
                        jz_runs[t] = float(jz_runs[e])
                        jz_tail_a.add(t)
                        if "jiazhu" not in tinst.flags:
                            tinst.flags.append("jiazhu")
            # ── 夹注 a/b 拆分（2026-08-25 用户定）────────────────
            # 确认成夹注段的格，整格实例替换为两个半宽实例：a=右子列、
            # b=左子列（读序：段内先 a 全部、后 b 全部——见
            # jiazhu_reading_order）。半边无墨（段末单半）不发实例。
            # flags 原样带上（含 jiazhu），下游据此区分字形/隔离训练。
            # 缝中心取 jz_runs：实测格是自己的、桥接格是邻格插值。
            for i, _c, inst in col_entries:
                if "jiazhu" not in inst.flags or i not in jz_pre \
                        or i not in jz_runs:
                    continue
                pre, ax0, ay0 = jz_pre[i]
                cx = jz_runs[i]
                cxi = int(round(cx))
                halves = []
                for sub, xs, xe in (("a", cxi, pre.shape[1]), ("b", 0, cxi)):
                    if sub == "b" and i in jz_tail_a:
                        continue      # 单字尾：b 侧只有残渣，不发实例
                    hp = pre[:, xs:xe]
                    ty, tx = np.nonzero(hp < BINARY_THRESHOLD_PATCH)
                    if ty.size < 30:
                        continue
                    tx0 = max(0, int(tx.min()) - TIGHT_MARGIN)
                    tx1 = min(hp.shape[1], int(tx.max()) + 1 + TIGHT_MARGIN)
                    ty0 = max(0, int(ty.min()) - TIGHT_MARGIN)
                    ty1 = min(hp.shape[0], int(ty.max()) + 1 + TIGHT_MARGIN)
                    hpatch = hp[ty0:ty1, tx0:tx1]
                    hinst = CharInstance(
                        id=inst.id + sub,
                        book=inst.book, page=inst.page, col=inst.col,
                        idx=inst.idx,
                        bbox=(ax0 + xs + tx0, ay0 + ty0,
                              ax0 + xs + tx1, ay0 + ty1),
                        cell_type="char",
                        ocr_text=None, ocr_confidence=0.0,
                        patch_path=f"patches/{page}/{col_no}_{i}{sub}.png",
                        ink_ratio=round(_patch_ink_ratio(hpatch), 4),
                        height=round(float(ty1 - ty0), 2),
                        width=round(float(tx1 - tx0), 2),
                        flags=list(inst.flags), sub=sub)
                    halves.append((hinst, hpatch))
                if halves:
                    jz_replaced.add(inst.id)
                    results.extend(halves)
        if jz_replaced:
            results = [r for r in results if r[0].id not in jz_replaced]
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
                    if defect_flags(inst.flags):
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


def jiazhu_reading_order(col_instances: list["CharInstance"]
                         ) -> list["CharInstance"]:
    """一列实例的**阅读顺序**（夹注读序的唯一权威，下游文本装配用它）。

    正文格按 idx 升序；**连续夹注段**（idx 连续的 jiazhu 格）作为整体
    插在段位上，段内先读右子列 a 全部（idx 升序）、再读左子列 b 全部
    ——双行小注先右行后左行（2026-08-25 用户定）。输入乱序也行。
    """
    by_idx: dict[int, list[CharInstance]] = {}
    for r in col_instances:
        by_idx.setdefault(r.idx, []).append(r)
    out: list[CharInstance] = []
    idxs = sorted(by_idx)
    k = 0
    while k < len(idxs):
        i = idxs[k]
        cells = by_idx[i]
        if any(r.sub for r in cells):
            # 收整个连续夹注段
            run = [i]
            while (k + 1 < len(idxs) and idxs[k + 1] == idxs[k] + 1
                   and any(r.sub for r in by_idx[idxs[k + 1]])):
                k += 1
                run.append(idxs[k])
            for sub in ("a", "b"):
                for j in run:
                    out.extend(r for r in by_idx[j] if r.sub == sub)
        else:
            out.extend(cells)
        k += 1
    return out


def load_index(phase4_dir: Path) -> list[CharInstance]:
    """读取 phase4_chars/index.jsonl。"""
    path = Path(phase4_dir) / "index.jsonl"
    with open(path, "r", encoding="utf-8") as f:
        return [CharInstance.from_json(line) for line in f if line.strip()]
