# -*- coding: utf-8 -*-
"""粘连切点「先认后切」实验的公共件（只读生产产物，不改任何生产代码）。

背景与设计：overview `项目进展/图片初步数字化/进度/Step3-逐字切分/05-高级切分算法.md`。

这里把三件事做成可复用的函数：
1. 从 `touching-cuts` 金标出发，对到**当下**产物（cells / cut_candidates / 列图），
   取出切点两侧的双格窗口（column 坐标）；
2. 各种切法（直线 / 现役缝 / 各候选 / 人工金标折线）→ 双格窗口的上下两张半字图；
3. 模板源：本书字形库真刻例（排除待测格自身）与字体渲染（I.Ming → Jigmo 兜底）。

坐标口径：
- 列图 = `column_image` 缓存（Step2 清理后列图），左上原点；
- 缝数组长度 = 内容窗口宽 `x_hi - x_lo`，下标 0 对应列图 x = `content_x[0]`；
- 金标 `y` / `polyline` 都是列图坐标；`polyline_to_seam(points, x_lo, x_hi)` 转成同口径缝。
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import cell_key, column_key, page_key  # noqa: E402
from open_guji_cv.core.step import RunContext  # noqa: E402
from open_guji_cv.core.workspace import glyph_db_path  # noqa: E402
from open_guji_cv.eval.touching import polyline_to_seam  # noqa: E402
from open_guji_cv.gold.store import GoldStore  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
import open_guji_cv.steps  # noqa: E402,F401  (注册 Step，materialize 需要)
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

SHARD = "char-segmentation/touching-cuts"
INK_TH = 128
OUT_ROOT = Path(__file__).resolve().parent / "out"   # 实验产出（不进 git，见 .gitignore 追加）


# ───────────────────────── 金标 → 当下产物 ─────────────────────────
@dataclass
class CutCase:
    id: str
    book: str
    page: int
    col: int
    verdict: str
    gold_y: float
    gold_poly: list | None
    char_above: str
    char_below: str
    col_h_gold: int
    cand_kind: str | None       # 「选切分方案」卡片裁决选中的候选 kind（没有则 None）
    # 对到当下产物
    k: int                      # boundary 下标（slot k 与 k+1 之间）
    cc: object                  # ColumnCells
    up: object                  # CellRec
    dn: object                  # CellRec
    cp: object | None           # CutPointCandidates（没有多候选时为 None）
    period: float
    x_lo: int
    x_hi: int
    _img: np.ndarray | None = field(default=None, repr=False)

    # 便利量
    @property
    def straight_y(self) -> float:
        return float(self.cc.boundaries[self.k])

    @property
    def content_w(self) -> int:
        return self.x_hi - self.x_lo

    @property
    def win_y0(self) -> int:
        return int(round(self.up.y0))

    @property
    def win_y1(self) -> int:
        return int(round(self.dn.y1))

    def has_chars(self) -> bool:
        return bool(self.char_above and self.char_below
                    and len(self.char_above) == 1 and len(self.char_below) == 1)


class Loader:
    """产物 / 缓存 / 金标的只读入口。"""

    def __init__(self):
        self.store = ProductStore()
        self.cache = ImageCache()
        self.gold = GoldStore()
        self._books: dict[str, object] = {}
        self._ctx: dict[str, RunContext] = {}
        self._cells: dict[tuple[str, int], object] = {}
        self._img: dict[tuple[str, int, int], np.ndarray | None] = {}

    def book(self, book: str):
        if book not in self._books:
            self._books[book] = load_book(book)
        return self._books[book]

    def ctx(self, book: str) -> RunContext:
        if book not in self._ctx:
            self._ctx[book] = RunContext(self.book(book), self.store, self.cache, log=lambda s: None)
        return self._ctx[book]

    def cells(self, book: str, page: int):
        key = (book, page)
        if key not in self._cells:
            self._cells[key] = self.store.read(book, "row_segment", page_key(page), "cells")
        return self._cells[key]

    def column_image(self, book: str, page: int, col: int) -> np.ndarray | None:
        key = (book, page, col)
        if key not in self._img:
            img = None
            p = self.cache.get(book, "column_image", column_key(page, col))
            if p is None:
                try:
                    p = self.ctx(book).materialize("column_image", column_key(page, col))
                except Exception:
                    p = None
            if p is not None:
                img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            self._img[key] = img
        return self._img[key]

    # ── 金标 ──
    def gold_items(self, books: Iterable[str] | None = None, verdicts: Iterable[str] | None = None,
                   need_chars: bool = False, need_poly: bool = False) -> list:
        items = [i for i in self.gold.list(SHARD) if i.status == "active" and not i.expected.get("tags")]
        if books:
            bs = set(books)
            items = [i for i in items if i.anchor.book in bs]
        if verdicts:
            vs = set(verdicts)
            items = [i for i in items if i.expected.get("verdict") in vs]
        if need_chars:
            items = [i for i in items if i.expected.get("char_above") and i.expected.get("char_below")]
        if need_poly:
            items = [i for i in items if i.expected.get("polyline") and len(i.expected["polyline"]) >= 2]
        return items

    def resolve(self, item, max_dev_frac: float = 0.45) -> tuple[CutCase | None, str]:
        """把一条金标对到当下的 cells。返回 (case, reason)。

        金标是按 (page, col, slot) 键的，但切分改过之后格位可能平移；这里按
        「离金标 y 最近的内部格线」找切点，再要求两侧都是 char 格。
        """
        a, ex = item.anchor, item.expected
        cells = self.cells(a.book, a.page)
        if cells is None:
            return None, "no_cells_product"
        cc = cells.column(a.col)
        if cc is None or not cc.ok or len(cc.cells) != len(cc.boundaries) - 1:
            return None, "column_not_ok"
        period = float(cc.period or cells.period or 0) or 1.0
        inner = list(enumerate(cc.boundaries))[1:-1]
        if not inner:
            return None, "no_inner_boundaries"
        cand_kind = ex.get("cand")
        if "y" in ex and ex["y"] is not None:
            gy = float(ex["y"])
            k, by = min(inner, key=lambda t: abs(t[1] - gy))
            if abs(by - gy) > max_dev_frac * period:
                return None, f"gold_far_from_boundary({abs(by - gy):.0f}px)"
        else:
            # 「选切分方案」裁决：没有 y，按 slot 对位（这类卡片是对当下候选裁的，格位不会漂）
            sa, sb = ex.get("slot_above"), ex.get("slot_below")
            k = next((i for i in range(1, len(cc.cells)) if cc.cells[i - 1].slot == sa and cc.cells[i].slot == sb), None)
            if k is None:
                return None, "slots_not_found"
            gy = float(cc.boundaries[k])
        up, dn = cc.cells[k - 1], cc.cells[k]
        if up.kind != "char" or dn.kind != "char":
            return None, f"not_char_char({up.kind}/{dn.kind})"
        cp = next((c for c in cc.cut_candidates if c.k == k), None)
        if cand_kind and (cp is None or not any(c.kind == cand_kind for c in cp.candidates)):
            return None, f"cand_kind_missing({cand_kind})"
        x_lo, x_hi = (int(round(cc.content_x[0])), int(round(cc.content_x[1]))) if cc.content_x \
            else (int(round(up.x0)), int(round(up.x1)))
        case = CutCase(
            id=item.id, book=a.book, page=a.page, col=a.col, verdict=ex.get("verdict", ""),
            gold_y=gy, gold_poly=ex.get("polyline"), char_above=ex.get("char_above", "") or "",
            char_below=ex.get("char_below", "") or "", col_h_gold=int(ex.get("col_h", 0) or 0),
            cand_kind=cand_kind, k=k, cc=cc, up=up, dn=dn, cp=cp, period=period, x_lo=x_lo, x_hi=x_hi)
        return case, "ok"

    def image_of(self, case: CutCase) -> np.ndarray | None:
        if case._img is None:
            case._img = self.column_image(case.book, case.page, case.col)
        return case._img


# ───────────────────────── 切法 → 缝 → 半字图 ─────────────────────────
def seam_straight(case: CutCase, y: float | None = None) -> np.ndarray:
    yy = case.straight_y if y is None else y
    return np.full(case.content_w, int(round(yy)), dtype=int)


def seam_gold(case: CutCase) -> np.ndarray:
    """人工金标缝：折线 > 「选切分方案」选中的候选 > 直线 y。"""
    if case.gold_poly and len(case.gold_poly) >= 2:
        s = polyline_to_seam(case.gold_poly, case.x_lo, case.x_hi)
        if len(s) == case.content_w:
            return np.asarray(s, dtype=int)
    if case.cand_kind and case.cp is not None:
        for c in case.cp.candidates:
            if c.kind == case.cand_kind:
                if c.y is None:
                    return seam_straight(case, case.cp.y)
                if len(c.y) == case.content_w:
                    return np.asarray(c.y, dtype=int)
    return seam_straight(case, case.gold_y)


def seam_chosen(case: CutCase) -> np.ndarray:
    """现役实际用的切法：上格的 seam_bottom；没有就是直线。"""
    sb = getattr(case.up, "seam_bottom", None)
    if sb and len(sb) == case.content_w:
        return np.asarray(sb, dtype=int)
    return seam_straight(case)


def seams_candidates(case: CutCase) -> list[tuple[str, np.ndarray]]:
    """产物里记的全部候选（kind, seam）。"""
    out: list[tuple[str, np.ndarray]] = []
    if case.cp is None:
        return [("straight", seam_straight(case))]
    for c in case.cp.candidates:
        if c.y is None:
            out.append((c.kind, seam_straight(case, case.cp.y)))
        elif len(c.y) == case.content_w:
            out.append((c.kind, np.asarray(c.y, dtype=int)))
    return out or [("straight", seam_straight(case))]


def window(case: CutCase, img: np.ndarray, pad: int = 0) -> tuple[np.ndarray, int, int]:
    """双格窗口（灰度）与它在列图里的 (y0, x0)。"""
    y0 = max(0, case.win_y0 - pad)
    y1 = min(img.shape[0], case.win_y1 + pad)
    return img[y0:y1, case.x_lo:case.x_hi], y0, case.x_lo


def side_masks(win_shape: tuple[int, int], seam: np.ndarray, y0: int) -> tuple[np.ndarray, np.ndarray]:
    """按缝把窗口分成上/下两个布尔掩膜（行 < seam 属上）。"""
    h, w = win_shape
    ys = np.arange(h)[:, None] + y0
    s = np.asarray(seam[:w])[None, :]
    above = ys < s
    return above, ~above


def half_patch(win: np.ndarray, mask: np.ndarray, margin: int = 2) -> np.ndarray | None:
    """把掩膜外的像素抹白，再紧裁到墨的外接框；无墨返回 None。"""
    g = win.copy()
    g[~mask] = 255
    ink = g < INK_TH
    if not ink.any():
        return None
    ys, xs = np.nonzero(ink)
    y0, y1 = max(0, ys.min() - margin), min(g.shape[0], ys.max() + 1 + margin)
    x0, x1 = max(0, xs.min() - margin), min(g.shape[1], xs.max() + 1 + margin)
    return g[y0:y1, x0:x1]


def ink_agreement(win: np.ndarray, seam_a: np.ndarray, seam_b: np.ndarray, y0: int) -> float:
    """两种切法在**墨像素**上的归属一致率（像素级，1.0 = 完全一样）。"""
    ink = win < INK_TH
    a, _ = side_masks(win.shape, seam_a, y0)
    b, _ = side_masks(win.shape, seam_b, y0)
    n = int(ink.sum())
    return 1.0 if n == 0 else float((a[ink] == b[ink]).mean())


# ───────────────────────── 模板源 ─────────────────────────
def _unpng(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    return (img < INK_TH).astype(np.uint8)


class GlyphIndex:
    """本书字形库（workspace 的 glyph.db）按 label 取真刻例，可排除待测格自身。"""

    def __init__(self, db_path: str | Path | None = None,
                 statuses: tuple[str, ...] = ("human", "align")):
        self.path = Path(db_path) if db_path else glyph_db_path()
        self.con = sqlite3.connect(str(self.path))
        q = ("select instance_id, source_id, page, col, idx, label, label_status from instances "
             "where label is not null and label != ''")
        self.by_char: dict[str, list[tuple]] = {}
        for iid, src, page, col, idx, label, st in self.con.execute(q):
            if st not in statuses:
                continue
            self.by_char.setdefault(label, []).append((iid, src, int(page), int(col), int(idx), st))
        self._patch_cache: dict[str, np.ndarray] = {}

    def has(self, ch: str) -> bool:
        return ch in self.by_char

    def count(self, ch: str) -> int:
        return len(self.by_char.get(ch, []))

    def patch(self, iid: str) -> np.ndarray:
        if iid not in self._patch_cache:
            row = self.con.execute("select patch_png from instances where instance_id=?", (iid,)).fetchone()
            self._patch_cache[iid] = _unpng(row[0]) if row else None
        return self._patch_cache[iid]

    def exemplars(self, ch: str, exclude: tuple[int, int, Iterable[int]] | None = None,
                  n: int = 5, seed: int = 0) -> list[np.ndarray]:
        """返回 ≤n 张 canonical 256² 二值图（1 = 墨）。

        exclude = (page, col, idxs)：排除同页同列、idx 在给定集合内的实例——
        也就是待测的那两格自己（vol01 与 v2 两个 source 的页码相同，都排）。
        """
        rows = list(self.by_char.get(ch, []))
        if exclude is not None:
            pg, col, idxs = exclude
            idxs = set(idxs)
            rows = [r for r in rows if not (r[2] == pg and r[3] == col and r[4] in idxs)]
        # human 优先，其余按确定性随机
        rng = random.Random(seed)
        rng.shuffle(rows)
        rows.sort(key=lambda r: 0 if r[5] == "human" else 1)
        out = []
        for r in rows[: n * 2]:
            p = self.patch(r[0])
            if p is not None and p.any():
                out.append(p)
            if len(out) >= n:
                break
        return out


class FontTemplates:
    """字体模板：I.Ming（传承字形）优先，Jigmo 兜底。渲染成 canonical 256² 二值。"""

    def __init__(self, font_dir: Path | None = None):
        from open_guji_cv.clustering.font_glyphs import FontRenderer
        fd = font_dir or (REPO / "fonts")
        self.renderers = []
        iming = fd / "iming" / "I.Ming-8.10.ttf"
        if iming.exists():
            self.renderers.append(("iming", FontRenderer([iming])))
        jig = [fd / "jigmo" / f for f in ("Jigmo.ttf", "Jigmo2.ttf", "Jigmo3.ttf") if (fd / "jigmo" / f).exists()]
        if jig:
            self.renderers.append(("jigmo", FontRenderer(jig)))
        self._cache: dict[str, tuple[str, np.ndarray] | None] = {}

    def render(self, ch: str) -> tuple[str, np.ndarray] | None:
        if ch not in self._cache:
            got = None
            for name, r in self.renderers:
                g = r.render(ch)
                if g is not None:
                    got = (name, (g < INK_TH).astype(np.uint8))
                    break
            self._cache[ch] = got
        return self._cache[ch]


# ───────────────────────── 识别器 ─────────────────────────
class Recognizer:
    """现役 CNN（分类头 + embedding 检索）的薄包装；输入 64² 归一图列表。"""

    def __init__(self):
        from open_guji_cv.clustering.cnn_candidates import shared
        self.cnn = shared()
        ok = self.cnn._ensure()
        if not ok:
            raise RuntimeError("CNN checkpoint / torch 不可用")
        self.classes = list(self.cnn._classes)

    def cls_topk(self, norms: list[np.ndarray], k: int = 10) -> list[list[tuple[str, float]]]:
        return self.cnn.topk_batch(norms, self.classes, k=k)

    def emb_topk(self, norms: list[np.ndarray], k: int = 10) -> list[list[tuple[str, float]]]:
        return self.cnn.emb_topk_batch(norms, self.classes, k=k)


def normalize(gray: np.ndarray) -> np.ndarray:
    from open_guji_cv.clustering.normalize import normalize_patch
    return normalize_patch(gray)


# ───────────────────────── 小工具 ─────────────────────────
def ink_bbox(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(binary)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def rank_of(target: str, topk: list[tuple[str, float]]) -> int | None:
    for i, (c, _) in enumerate(topk):
        if c == target:
            return i + 1
    return None


def jdump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
