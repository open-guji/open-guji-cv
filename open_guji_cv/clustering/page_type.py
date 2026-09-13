"""页型判别：这一页该不该套刻本网格，套哪种。

为什么需要
----------
管线原先**完全没有页型判断**：profile 说每半页 9 列，就一律按 9 列切。
封面、书签、空白页、牌记页照套，结果是纯垃圾——实测 vol01/2（书签页，
整页只有一条书名）被切成 126 个块、`bad_seg` 94%；vol01/158（近空白页，
只有一列「春秋類一」）格高锁到 37.8px（真值 114），切出 0 个字。全书
394 页里有 7 页这样，占 1.8%。

分类的第一刀是「有没有界行栏格」（2026-09-13 用户定）
------------------------------------------------------
**有界行分成九列的就算 body**；body 底下再按栏内是什么分子类：

    body（有界行栏格，套标准九列网格）
      ├─ 正常    栏内有正文字
      ├─ blank   栏内没字（版框界行都印着，只有版心有字）
      ├─ toc     目录
      └─ roster  职名
    skip（没有正文栏格，不套网格）
      ├─ cover / label / colophon

**`blank` 是 body 的子类，不是 skip**（2026-09-13 订正）。原先把它摆在
`SKIP_TYPES` 里与 body 平级是分类学错了：空栏页的界行是齐的、九列切得出来，
只是栏内无字——该套网格，正常产出一个"各格皆空"的页，而不是跳过。
订正前的后果见下面 `BLANK_*` 的注释。

三种网格策略
------------
判别的落点不是文学分类，而是**网格该怎么用**：

- `skip`     不套网格。封面 / 书签 / 牌记——这些页没有正文栏格，
             任何列拟合都是无中生有。
- `custom`   套网格但列数不同。上諭、表文字大列宽，列数少于正文。
- `standard` 套现有的 9 列刚性网格。正文 / 空栏 / 职名 / 目录四类共用它
             （它们的差别是**列内**内容，由下游各层判，不在这里重复）。

判别靠版面结构，不靠文字内容
----------------------------
转写本身依赖切分，拿它判页型是循环论证；且非正文页的转写质量最差
（封面页的转写基本是乱码），最需要判别的地方恰好最不可信。所以这里只
用**结构量**：界行条数、墨量、字号、连通体数、墨的空间分布。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

SCHEMA_VERSION = 1

BINARY_T = 128

# 页型。分类的第一刀是「有没有界行栏格」，见模块头。
PAGE_TYPES = ("cover", "label", "blank", "colophon",
              "edict", "body", "roster", "toc", "uncertain")
SKIP_TYPES = ("cover", "label", "colophon")
CUSTOM_TYPES = ("edict",)
# body 底下的子类：都有界行栏格、都套标准九列网格。`blank` 在这里而不在
# SKIP_TYPES——空栏页界行是齐的，该正常切、产出空页（2026-09-13 用户定）。
STANDARD_TYPES = ("body", "blank", "roster", "toc")
BODY_SUBTYPES = STANDARD_TYPES

POLICIES = ("skip", "custom", "standard")


def policy_of(page_type: str) -> str | None:
    if page_type in SKIP_TYPES:
        return "skip"
    if page_type in CUSTOM_TYPES:
        return "custom"
    if page_type in STANDARD_TYPES:
        return "standard"
    return None                      # uncertain：评测跳过


@dataclass
class PageTypeLabel:
    book: str
    page: str
    page_type: str
    label_origin: str = "human"
    note: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.page_type not in PAGE_TYPES:
            raise ValueError(f"未知页型 {self.page_type!r}，应为 {PAGE_TYPES}")

    @property
    def key(self) -> str:
        return f"{self.book}/{self.page}"

    @property
    def policy(self) -> str | None:
        return policy_of(self.page_type)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PageTypeLabel":
        d = dict(d)
        d.pop("schema_version", None)
        return cls(**d)


def load_labels(path: str | Path) -> list[PageTypeLabel]:
    return [PageTypeLabel.from_dict(r)
            for r in json.loads(Path(path).read_text(encoding="utf-8"))]


def save_labels(items: list[PageTypeLabel], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=1),
        encoding="utf-8")


# ── 结构特征 ──────────────────────────────────────────────

def page_features(gray: np.ndarray) -> dict:
    """页面结构特征。全部与文字内容无关，只看墨的几何分布。"""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    b = (gray < BINARY_T).astype(np.uint8)
    ink = float(b.mean())

    # 界行/版框竖线：够长的竖直连续段
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(h * 0.3))))
    vcov = cv2.dilate(cv2.erode(b, kv), kv).sum(axis=0) / h
    xs = np.where(vcov > 0.5)[0]
    n_vline = 0
    if len(xs):
        n_vline = 1 + int((np.diff(xs) > 6).sum())

    # 字形连通体：剔掉线状与噪点之后的"像字的块"
    n, _, st, _ = cv2.connectedComponentsWithStats(b, 8)
    glyph_h = glyph_w = 0.0
    n_glyph = 0
    if n > 1:
        a = st[1:]
        area = a[:, 4].astype(float)
        ch, cw = a[:, 3].astype(float), a[:, 2].astype(float)
        ok = ((area > 0.00004 * h * w) & (area < 0.01 * h * w)
              & (ch < 0.25 * h) & (cw < 0.25 * w))
        g = a[ok]
        n_glyph = int(len(g))
        if n_glyph >= 8:
            glyph_h = float(np.median(g[:, 3]) / h)
            glyph_w = float(np.median(g[:, 2]) / w)

    # 字墨（去掉长线之后）的空间占用：书签/牌记页的字挤在一角
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(w * 0.3)), 1))
    lines = cv2.dilate(cv2.erode(b, kv), kv) | cv2.dilate(cv2.erode(b, kh), kh)
    txt = b & (1 - lines)
    txt_ink = float(txt.mean())
    cx, cy = txt.sum(axis=0).astype(float), txt.sum(axis=1).astype(float)

    def cover(v: np.ndarray) -> float:
        """墨占据了这个方向上多大比例的幅面（按 5% 峰值门限）。"""
        if v.max() <= 0:
            return 0.0
        return float((v > v.max() * 0.05).mean())

    return {
        "ink": round(ink, 5),
        "txt_ink": round(txt_ink, 5),
        "n_vline": n_vline,
        "n_glyph": n_glyph,
        "glyph_h": round(glyph_h, 5),
        "glyph_w": round(glyph_w, 5),
        "x_cover": round(cover(cx), 4),
        "y_cover": round(cover(cy), 4),
    }


# ── 判别阈值 ──────────────────────────────────────────────
# 全部按「正文类页的极值」留出余量定，不是拟合出来的：
#   正文类 373 页实测 y_cover 最小 0.275、n_glyph 最小 60、x_cover 最小 0.265
#
# ⚠️ BLANK_* 的**代价方向在 2026-09-13 翻转了**。blank 改归 body 子类之后，
# 判成 blank 不再意味着"跳过这一页"——两边都套九列网格，只是走不走
# 「栏内无字」这条快路。所以：
#   · 漏判（空栏页当正常正文页）不再是静默丢数据，只是白跑一遍切分；
#   · 误判（正文页当空栏页）才是要防的，但它也不再"丢页"，只是这页的
#     字会被当成没有——仍属零容忍，所以门槛继续按正文极值留余量，不放宽。
# 这两个门槛**没动过**（仍是 40 / 0.15），改的只是它们的后果。
#
# 已知漏判：vol01 p62(n_glyph=49,y_cover=0.298) / p158(54,0.263) /
# p206(40,0.171)——界行连通体本身撑过了 n_glyph 门槛。这三页现在走
# 「正常 body」路线并靠书级 period 先验正常产出空页（见 column_gate），
# 所以**漏判不再有后果**，不必为了它们去动门槛（现值已贴着正文分布
# 下沿，抬门槛会开始误伤正文页；且样本只有 3 页，n 太小易过拟合）。
BLANK_Y_COVER = 0.15       # 墨只占页高此比例以下 → 空栏页（正文最小 0.275）
BLANK_N_GLYPH = 40         # 且字形连通体少于此（正文最小 60）
COVER_N_GLYPH = 30         # 封面：大字撑破字形尺寸筛，只剩零星连通体
COVER_X_COVER = 0.35
LABEL_X_COVER = 0.25       # 书签：窄长一条（正文最小 0.265）
LABEL_Y_COVER = 0.50


def classify_page_type(gray: np.ndarray) -> tuple[str, str]:
    """返回 (页型, 网格策略)。判不准时返回 ("body", "standard")——
    **默认走正常网格**，因为误跳过一页正文的代价远大于多切一页废页。

    判三种页型，它们与正常正文页在结构上分得干净：

    - `blank`  **body 的子类**（策略 standard，不是 skip）：墨只占页高 15%
               以下且字形连通体 <40。空栏页界行是齐的、九列切得出来，
               只是栏内无字，该正常切、产出空页。见模块头与 BLANK_* 注释。
    - `cover`  封面的大字尺寸超出字形筛（n_glyph 骤降到个位数），且墨
               挤在页面中部一条窄带里。**skip**。
    - `label`  书签：墨占宽度 <25%、占高度 >50%，一条竖长带。**skip**。

    没有 `colophon`（牌记）与 `edict`（上諭）的规则——不是忘了，是**证据
    不足以立规则**：全书各只有 1 例，且它们的结构量与最稀疏的目录页重叠
    （牌记 vol01/205 的 x_cover=0.496、n_glyph=90，目录 vol01/182 是
    0.616/90，目录 vol01/61 是 0.265/60）。硬立规则会把稀疏目录页误跳过，
    那是丢真数据，比多切一页废页严重得多。这两类记在 known_limitation 里。
    """
    f = page_features(gray)
    if f["n_glyph"] < BLANK_N_GLYPH and f["y_cover"] < BLANK_Y_COVER:
        return "blank", "standard"
    if f["n_glyph"] < COVER_N_GLYPH and f["x_cover"] < COVER_X_COVER:
        return "cover", "skip"
    if f["x_cover"] < LABEL_X_COVER and f["y_cover"] > LABEL_Y_COVER:
        return "label", "skip"
    return "body", "standard"

# ── 切分后的页型细化（正文/职名判别）──────────────────────
ROSTER_EL_T = 0.5          # 弹性列比例达到此值才判 roster。阈值从金标极端定：
                           # 修正金标后 body 的弹性列比例最大 0.22（vol02/179、
                           # 131 各有 2/9 列被误判弹性），0.5 留了 2.3 倍余量，
                           # 金标上 roster 检出 41/44、body 误判 0。漏掉的 3 页
                           # （p90 压缩型职名 el=0.11、p107、p89 段首）都是
                           # 弹性列检出不足的已知案例，归 body 是可接受方向。
                           # 方向性代价不对称：正文误判成职名 = 该页被排除在
                           # 正文指标/正文优化之外（静默损失，零容忍）；
                           # 职名漏判成正文 = 噪声页混进正文集（可事后标记）。
                           # 所以存疑一律归 body
ROSTER_EL_MIN = 3          # 至少这么多条弹性列（绝对数，防少列页碰运气）


# ── v2：切不动的页（职名/目录）──────────────────────────────
# 判据是「弹性 DP 无解的列占比」，不是 refine_page_type 那个「弹性列比例」。
# 换量的原因是**观测对象没了**：refine_page_type 读的是切成功之后每列的
# `layout`，而 v2 里职名页 44 页有 38 页**整页一列都没切出来**（396 列只有
# 43 列 ok）——要判的恰恰是没有 cells 可看的页。所以从「切出来什么样」
# 改成「切不出来」，这个量对整页无解的页反而最强。
#
# 2026-09-13 在 page-type 金标 394 页上实测（products/ 现成产物，未重跑）：
#
#   页型              n     无解列比例 min/中位/max   >0 的页数
#   body (vol01+02)  294    0.000 / 0.000 / 0.000       0
#   roster (vol01)    44    0.000 / 1.000 / 1.000      39
#   toc    (vol01)    47    0.000 / 0.000 / 1.000       7
#
# **294 页正文没有一列无解**，分离是完全的、不是留余量——所以「body 误判
# 必须 0」这条红线由判据本身保证，不靠调阈值。门槛取 >0 即判，不设比例
# 阈值：任何一个正数在正文页上都没出现过，设比例反而是凭空收紧。
#
# **不细分 roster / toc**（用户 2026-09-13 定）：toc 有 7 页（p159/165/195/
# 196/198/200/202）与 roster 在这个量上完全重叠，其中 3 页整页无解，分不开。
# refine_page_type 的注释里早写明「toc 不判」，同一个道理。所以这里判出的
# 类别叫**「版式未支持」**，只断言「非正文、现有 21 格先验切不了」，不谎称
# 能分文学类别。细分是 keben_roster.yaml 那件事。
UNSUPPORTED_LAYOUT_ERROR = "弹性 DP 无解"


def unsupported_layout_columns(columns: list[dict]) -> int:
    """这一页有几列是「版式未支持」而无解的。

    只数 `UNSUPPORTED_LAYOUT_ERROR` 这一种拒因——DP 无解还有别的来路
    （未过交接闸、页级 period 缺失），那些是上游的事，混进来会把闸1 漏判的
    空白页（vol01 p62/p158/p206，Step2 估不出周期）也算成版式未支持。
    """
    return sum(1 for c in columns
               if not c.get("ok") and c.get("error") == UNSUPPORTED_LAYOUT_ERROR)


def refine_page_type(result: dict) -> str:
    """用**切分产物**把 body 细分出 roster（职名页）。

    ⚠️ **v1 专用**。v2 链上判职名页走 `unsupported_layout_columns()`，
    原因见其上方注释（这里读的 `columns[i].layout` 是 v1 `grid_segment.py`
    的产物形状，v2 `products/kinds/cells.py` 没有这个字段；更要紧的是
    v2 职名页整页切不出来，压根没有列可看）。

    classify_page_type 在切分前跑，只看得到灰度统计，分不开 body/roster/
    toc（实测 roster 31 页、toc 47 页全被归into body）。切分之后强特征
    就有了：职名页的列几乎全是弹性列（字距拉开），正文页几乎没有——
    修正金标后两个分布完全分开（body max 0.22 vs roster p25 1.00）。

    toc **不判**，如实记录：卷首页（标题短列 + 正文列混合）与 toc 在
    列占用形态上真重叠（body fill 最低 0.24 vs toc 最高 0.65），
    没有不重叠的量之前不设阈值。

    返回细化后的页型；非 body 或证据不足时原样返回。
    """
    ptype = result.get("page_type", "body")
    if ptype != "body":
        return ptype
    cols = [c for c in result.get("columns", []) if not c.get("skipped")]
    if len(cols) < ROSTER_EL_MIN:
        return ptype
    n_el = sum(1 for c in cols if c.get("layout") == "elastic")
    if n_el >= ROSTER_EL_MIN and n_el / len(cols) >= ROSTER_EL_T:
        return "roster"
    return ptype
