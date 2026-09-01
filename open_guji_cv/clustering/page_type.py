"""页型判别：这一页该不该套刻本网格，套哪种。

为什么需要
----------
管线原先**完全没有页型判断**：profile 说每半页 9 列，就一律按 9 列切。
封面、书签、空白页、牌记页照套，结果是纯垃圾——实测 vol01/2（书签页，
整页只有一条书名）被切成 126 个块、`bad_seg` 94%；vol01/158（近空白页，
只有一列「春秋類一」）格高锁到 37.8px（真值 114），切出 0 个字。全书
394 页里有 7 页这样，占 1.8%。

八种页型与三种网格策略
----------------------
判别的落点不是文学分类，而是**网格该怎么用**：

- `skip`     不套网格。封面 / 书签 / 空白 / 牌记——这些页没有正文栏格，
             任何列拟合都是无中生有。
- `custom`   套网格但列数不同。上諭、表文字大列宽，列数少于正文。
- `standard` 套现有的 9 列刚性网格。正文 / 职名 / 目录三类共用它
             （它们的差别是**列内**字距，由 column-layout 那一层判，
             不在这里重复）。

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

# 八种页型。前四种没有正文栏格，后四种有。
PAGE_TYPES = ("cover", "label", "blank", "colophon",
              "edict", "body", "roster", "toc", "uncertain")
SKIP_TYPES = ("cover", "label", "blank", "colophon")
CUSTOM_TYPES = ("edict",)
STANDARD_TYPES = ("body", "roster", "toc")

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
BLANK_Y_COVER = 0.15       # 墨只占页高此比例以下 → 空白页（正文最小 0.275）
BLANK_N_GLYPH = 40         # 且字形连通体少于此（正文最小 60）
COVER_N_GLYPH = 30         # 封面：大字撑破字形尺寸筛，只剩零星连通体
COVER_X_COVER = 0.35
LABEL_X_COVER = 0.25       # 书签：窄长一条（正文最小 0.265）
LABEL_Y_COVER = 0.50


def classify_page_type(gray: np.ndarray) -> tuple[str, str]:
    """返回 (页型, 网格策略)。判不准时返回 ("body", "standard")——
    **默认走正常网格**，因为误跳过一页正文的代价远大于多切一页废页。

    只判三种「必须跳过」的页型，它们与正文类在结构上分得干净：

    - `blank`  墨只占页高 15% 以下且字形连通体 <40。正文类 373 页里
               y_cover 最小 0.275、n_glyph 最小 60，两条都有一倍余量。
    - `cover`  封面的大字尺寸超出字形筛（n_glyph 骤降到个位数），且墨
               挤在页面中部一条窄带里。
    - `label`  书签：墨占宽度 <25%、占高度 >50%，一条竖长带。

    没有 `colophon`（牌记）与 `edict`（上諭）的规则——不是忘了，是**证据
    不足以立规则**：全书各只有 1 例，且它们的结构量与最稀疏的目录页重叠
    （牌记 vol01/205 的 x_cover=0.496、n_glyph=90，目录 vol01/182 是
    0.616/90，目录 vol01/61 是 0.265/60）。硬立规则会把稀疏目录页误跳过，
    那是丢真数据，比多切一页废页严重得多。这两类记在 known_limitation 里。
    """
    f = page_features(gray)
    if f["n_glyph"] < BLANK_N_GLYPH and f["y_cover"] < BLANK_Y_COVER:
        return "blank", "skip"
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


def refine_page_type(result: dict) -> str:
    """用**切分产物**把 body 细分出 roster（职名页）。

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
