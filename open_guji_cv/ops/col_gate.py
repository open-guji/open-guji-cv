"""R6 整页／整列丢字检查（GUJI-661）：Step3 切完后，拿原图的墨对一遍切出来的列与格。

两种毛病，两把尺子，都只读 Step3 产物（`cells`）和原图，不依赖 Step4 以后：

* `col_missing` 整列没切出：版心里有一条够宽、够黑的竖带，落在所有已切列的横向范围之外
  （vol03 57:1 那种）。先用「又细又长」的开运算抹掉界行与版框，再看剩下的墨在 x 上的分布。
* `dropped` 丢字：某列的列带里，有「单字墨段」（高 0.45–1.35 格，口径与
  `scripts/eval_char_drop.col_runs` 一致）没被任何非 blank 格盖住一半（窄切、整列错位、
  格被记成空，都落在这一类）。

只报告，不改产物；出口闸（`collect_exit`）据此要求「每一条要么修好，要么登记 `seg_bad` 交 M10」。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..utils.image_io import imread as cv_imread

BIN_THR = 128           # 灰度低于此算墨（殿本 1-bit，0 = 墨）
RUN_INK = 0.06          # 行墨占列带宽这么多才算有墨（同 eval_char_drop）
RUN_MIN_H = 14
RUN_GAP = 6
SEG_LO, SEG_HI = 0.45, 1.35
COVER = 0.5
FILL_LO, FILL_HI = 0.10, 0.55   # 墨段填充率：低于下限是污渍碎点，高于上限是版框粗条
THICK = 21               # 抹掉比这更粗的黑块（笔画粗约 8–14 px，版框折角 30 px 以上）
EXTENT_MIN = 0.45        # 墨段横向跨度占列带宽的下限
LCC_MIN = 0.05           # 最大连通体占墨段框的比例下限（字的笔画连成大块，污渍不会）
MISSING_W = 0.6         # 竖带宽度 ≥ 这么多倍列宽才算「一列」
MISSING_INK = 0.75      # 竖带墨量 ≥ 这么多倍「中位列」墨量（真缺一列约 1 倍；书口边缘字约 0.5–0.7）
EDGE_MARGIN = 0.12      # 列的横向范围两侧各放宽这么多倍列宽再判「在外」


@dataclass
class Finding:
    kind: str                       # col_missing | dropped
    page: int
    col: int | None = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "page": self.page, "col": self.col, **self.detail}


def _runs(proj: np.ndarray, width: float, cell_h: float) -> list[tuple[int, int]]:
    on = proj > width * RUN_INK
    out, s = [], None
    for y, v in enumerate(on):
        if v and s is None:
            s = y
        if not v and s is not None:
            out.append([s, y])
            s = None
    if s is not None:
        out.append([s, len(on)])
    out = [r for r in out if r[1] - r[0] >= RUN_MIN_H]
    merged: list[list[int]] = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= RUN_GAP:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))
    return [(r[0], r[1]) for r in merged if SEG_LO * cell_h <= r[1] - r[0] <= SEG_HI * cell_h]


def _charlike(box: np.ndarray) -> bool:
    """墨段像不像字：污渍是碎点（最大连通体占不到框的一小块），版框粗条是大黑块（填充率过高）。"""
    fill = float(box.mean())
    if not (FILL_LO <= fill <= FILL_HI):
        return False
    xs = np.where(box.sum(axis=0) >= 2)[0]
    if xs.size == 0 or (xs[-1] - xs[0] + 1) / box.shape[1] < EXTENT_MIN:
        return False                       # 窄竖条（版框折角的竖边）不是字
    n, _, stats, _ = cv2.connectedComponentsWithStats(box, connectivity=8)
    big = int(stats[1:, cv2.CC_STAT_AREA].max()) if n > 1 else 0
    return big / box.size >= LCC_MIN


def _column_geometry(cols: list[dict], width: int) -> list[dict]:
    """每列在原图上的横向范围与有字格的 y 区间（非 blank 的格：正文与夹注）。

    Step3 的 `quad_page` 横向是镜像的（页内从右往左数列，x 按 `宽 − x` 记），读原图要翻回来。"""
    out = []
    for c in cols:
        xs, ys, chars = [], [], []
        for ce in c.get("cells") or []:
            q = ce.get("quad_page")
            if not q:
                continue
            qx = [p[0] for p in q]
            qy = [p[1] for p in q]
            xs += qx
            ys += qy
            if ce.get("kind") != "blank":
                chars.append((min(qy), max(qy)))
        if xs:
            out.append({"col": c.get("col"), "x0": width - max(xs), "x1": width - min(xs), "y0": min(ys), "y1": max(ys),
                        "chars": chars})
    return out


def _ink(gray: np.ndarray) -> np.ndarray:
    return (gray < BIN_THR).astype(np.uint8)


def check_page(gray: np.ndarray, page: int, step3: dict) -> list[Finding]:
    """`step3` 是 row_segment 产物里的 `cells`（含 `columns`、`period`）。"""
    cols = step3.get("columns") or []
    period = float(step3.get("period") or 0)
    ink = _ink(gray)
    H, W = ink.shape
    geo = _column_geometry(cols, W)
    if not geo or period <= 0:
        return []
    out: list[Finding] = []
    widths = sorted(g["x1"] - g["x0"] for g in geo)
    cw = float(widths[len(widths) // 2])
    top = int(max(0, min(g["y0"] for g in geo)))
    bot = int(min(H, max(g["y1"] for g in geo)))

    # ① 丢字：列带内的单字墨段没被字格接住。先抹掉横向粗条（版框折角、界行横线），不然框条会被当成一个字
    bars = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(cw * 0.9), 5)))
    blobs = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((THICK, THICK), np.uint8))   # 比笔画粗得多的黑块：版框折角
    ink = ink & (1 - cv2.dilate(np.maximum(bars, blobs), np.ones((9, 9), np.uint8)))
    for g in geo:
        x0, x1 = int(max(0, g["x0"])) + 4, int(min(W, g["x1"])) - 4
        if x1 - x0 < 8:
            continue
        proj = ink[:, x0:x1].sum(axis=1).astype(float)
        cov = np.zeros(H, dtype=bool)
        for a, b in g["chars"]:
            cov[int(max(0, a)):int(min(H, b))] = True
        lost = [r for r in _runs(proj, float(x1 - x0), period)
                if cov[r[0]:r[1]].mean() < COVER and _charlike(ink[r[0]:r[1], x0:x1])]
        if lost:
            out.append(Finding("dropped", page, g["col"], {"n": len(lost), "runs": [list(map(int, r)) for r in lost[:8]]}))

    # ② 整列没切出：抹掉界行／版框后，框内、已切列之外还有够黑够宽的竖带
    body = ink[top:bot]
    kh = max(15, int(period * 1.5))
    lines = cv2.morphologyEx(body, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, kh)))
    lproj = lines.sum(axis=0).astype(float)
    tall = np.where(lproj > 0.6 * body.shape[0])[0]       # 贯穿版心的竖线 = 版框
    gx0, gx1 = min(g["x0"] for g in geo), max(g["x1"] for g in geo)
    left = [int(t) for t in tall if t <= gx0 + 0.1 * cw]
    right = [int(t) for t in tall if t >= gx1 - 0.1 * cw]
    frame_l = max(left) if left else 0          # 最靠内的那条版框线；找不到就不设界
    frame_r = min(right) if right else W
    thick = cv2.dilate(lines, np.ones((1, 7), np.uint8))
    text = body & (1 - thick)
    xproj = text.sum(axis=0).astype(float)
    inside = np.zeros(W, dtype=bool)
    for g in geo:
        inside[int(max(0, g["x0"] - EDGE_MARGIN * cw)):int(min(W, g["x1"] + EDGE_MARGIN * cw))] = True
    col_mass = sorted(float(xproj[int(max(0, g["x0"])):int(min(W, g["x1"]))].sum()) for g in geo)
    med_mass = col_mass[len(col_mass) // 2] or 1.0
    k = max(3, int(cw * 0.08))
    sm = np.convolve(xproj, np.ones(k) / k, mode="same")
    on = (sm > float(body.shape[0]) * 0.02) & ~inside
    on[: frame_l + 1] = False
    on[frame_r:] = False
    s = None
    for x in range(W + 1):
        v = on[x] if x < W else False
        if v and s is None:
            s = x
        elif not v and s is not None:
            w = x - s
            mass = float(xproj[s:x].sum())
            if w >= MISSING_W * cw and mass >= MISSING_INK * med_mass:
                out.append(Finding("col_missing", page, None, {"x0": s, "x1": x, "mass_ratio": round(mass / med_mass, 2)}))
            s = None
    return out


def scan_book(book: str, pages: list[int] | None = None, store=None) -> tuple[list[dict], int]:
    """整册（或指定页）扫一遍：→ (findings 的 dict 列表, 扫了几页)。读 Step3 `row_segment` 产物与原图。"""
    from ..core.book import load_book
    from ..products.store import ProductStore
    bk = load_book(book)
    st = store or ProductStore()
    keys = [f"p{p:04d}" for p in pages] if pages else st.keys(book, "row_segment")
    found: list[dict] = []
    n = 0
    for k in keys:
        prod = st.read_raw(book, "row_segment", k)
        page = int(k[1:])
        try:
            img = cv_imread(str(bk.raw_path(page)), cv2.IMREAD_GRAYSCALE)
        except FileNotFoundError:   # 缺原图同旧口径（cv2.imread 返回 None）：跳过
            img = None
        if prod is None or img is None:
            continue
        n += 1
        found += [f.as_dict() for f in check_page(img, page, prod["cells"])]
    return found, n
