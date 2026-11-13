"""切分筛查：只读产物与列图，各书通用，找出要看图的列与页（A22 F4①②、F7、F8，2026-11-10）。

设计：Claude Doc《切分框架改进详细设计（F1–F8）》F4 节；命令 `scripts/seg_screen.py`。
第一期只出报告，不进闸、不改产物；准了再把 ①② 升进 row_segment_gate／column_gate（第二期）。

| 项 | 名 | 判据 |
|---|---|---|
| ① | `edge_ink` | 列图上第一格之上、最后一格之下（版框以内），有墨行合计 > 0.5 格高（列首或列尾漏切） |
| ②a | `colnet_page` | 页内某正文列文字带宽 < 0.7 或 > 1.3 倍本页中位（整页列网错，常漏首列再劈出窄条） |
| ②b | `layout_col_shift` | 格位表列号整页挪 ±1 后对上的列明显更多（表把整页列号错了一列） |
| F7 | `pitch_free_ignored` | 表行写了 `pitch: free`，最后选中的格网却是挤格补线（`layout_unmerge`），pitch 没起作用 |
| F8 | `seal_blank` | seed_admit 会按印框记空的格（`occlusion.page_seal_blank`），本机跑到 cell_shrink 就能看 |
"""
from __future__ import annotations

import numpy as np

EDGE_INK_FRAC = 0.5        # 端外有墨行 > 这么多格高才报
EDGE_ROW_MIN = 0.02        # 一行墨宽 < 列宽这么多不算（尘点）
FRAME_ROW = 0.5            # 一行墨宽 ≥ 列宽这么多算框线行
FRAME_NEAR = 3             # 框线行上下这么多行也不算（框线毛边）
COLNET_LO, COLNET_HI = 0.7, 1.3
SHIFT_MIN = 2              # 挪一列后要多对上至少这么多列，
SHIFT_FRAC = 0.5           # 且多对上的列数 ≥ 本页表行数的这么多（整页挪了才报，一两列偶合不报）


# ── ① 列首列尾漏墨 ───────────────────────────────────────────────────────────

def edge_ink(gray: np.ndarray, col_cells, ink_threshold: int = 128) -> dict | None:
    """一列（`ColumnCells` + 列图灰度）→ `{"top": 行数, "bottom": 行数, "period": …}`；两端都不超 → None。

    只看版框以内（`border_top`～`border_bottom`）、文字带（`content_x`）以内。框线行与其毛边不算。"""
    cells = [c for c in col_cells.cells]
    period = col_cells.period or 0.0
    if not cells or period <= 0:
        return None
    h, w = gray.shape[:2]
    x0, x1 = (int(col_cells.content_x[0]), int(col_cells.content_x[1])) if col_cells.content_x else (0, w)
    x0, x1 = max(0, x0), min(w, max(x1, x0 + 1))
    cw = x1 - x0
    row = (gray[:, x0:x1] < ink_threshold).sum(axis=1)
    frame = row >= FRAME_ROW * cw
    near = frame.copy()
    for d in range(1, FRAME_NEAR + 1):
        near[d:] |= frame[:-d]
        near[:-d] |= frame[d:]
    inky = (row >= max(2, EDGE_ROW_MIN * cw)) & ~near
    top_lim = max(0, int(col_cells.border_top or 0))
    bot_lim = min(h, int(col_cells.border_bottom if col_cells.border_bottom is not None else h))
    first = int(min(c.y0 for c in cells))
    last = int(max(c.y1 for c in cells))
    top = int(inky[top_lim:max(top_lim, first)].sum())
    bottom = int(inky[min(bot_lim, last):bot_lim].sum())
    lim = EDGE_INK_FRAC * period
    if top <= lim and bottom <= lim:
        return None
    return {"top": top, "bottom": bottom, "period": round(period, 1)}


# ── ②a 整页列网错 ───────────────────────────────────────────────────────────

def colnet_page(gate) -> list[dict]:
    """`GateManifest` → 列宽异常的正文列 `[{col, width, ratio}]`；空 = 正常。

    夹注豁免列（flags 里有「豁免」）、闸拒收的非正文列不算。"""
    med = gate.median_width
    if not med:
        return []
    out = []
    for c in gate.columns:
        if not c.admitted or any("豁免" in f for f in c.flags):
            continue
        r = c.band_width / med
        if r < COLNET_LO or r > COLNET_HI:
            out.append({"col": c.col, "width": round(c.band_width, 1), "ratio": round(r, 2)})
    return out


# ── ②b 格位表整页错一列 ─────────────────────────────────────────────────────

def _char_slots(col_cells) -> frozenset:
    return frozenset(c.slot for c in col_cells.cells if c.kind != "blank")


def layout_col_shift(page_cells, layout_rows: dict[int, dict]) -> dict | None:
    """一页的切分（`PageCells`）与本页格位表行 `{列: 行}` → 挪一列明显更对得上时 `{"shift", "match0", "match"}`。"""
    if not layout_rows:
        return None
    got = {cc.col: _char_slots(cc) for cc in page_cells.columns if cc.ok}

    def match(d: int) -> int:
        n = 0
        for col, row in layout_rows.items():
            s = got.get(col + d)
            if s is not None and s and s == frozenset(int(x) for x in row.get("slots") or []):
                n += 1
        return n
    m0 = match(0)
    best = max((-1, 1), key=match)
    mb = match(best)
    if mb - m0 >= max(SHIFT_MIN, SHIFT_FRAC * len(layout_rows)):
        return {"shift": best, "match0": m0, "match": mb, "cols": len(layout_rows)}
    return None


# ── F7 pitch free 没生效 ────────────────────────────────────────────────────

def pitch_free_ignored(col_cells, layout_row: dict | None) -> bool:
    return bool(layout_row and layout_row.get("pitch") == "free"
                and any(str(f).startswith("layout_unmerge") for f in col_cells.flags))


# ── F4③ 列端格只有框条（表说有字的端格也查）──────────────────────────────────

FRAME_ONLY_NEAR = 0.2     # 端格里的墨全落在离上／下版框线这么多格高以内，且有一行够宽（≥ FRAME_ROW）＝ 只是框条
FRAME_ONLY_SPECK = 0.08   # 墨宽 < 列宽这么多的行当霉点，不算（史記 04 p125、殿本 vol28 p102 都有）


def edge_frame_only(gray: np.ndarray, col_cells, ink_threshold: int = 128) -> list[int]:
    """物理首／末格（非 blank）里的墨只是版框线 → 返回这些格的 slot（P5 判据：这种格该记空）。

    条件：格里有墨行（≥ FRAME_ONLY_SPECK 列宽，更窄的当霉点）；所有这些墨行离对应的版框线（`border_top`／`border_bottom`，列图坐标）
    ≤ FRAME_ONLY_NEAR 格高；其中至少一行墨宽 ≥ FRAME_ROW。版框线没探到（None）的一端不查。
    只看墨宽会把「一」「二」的长横当框线（殿本 vol28 量出 4 例），所以要贴着框线。"""
    cells = sorted(col_cells.cells, key=lambda c: c.y0)
    if not cells:
        return []
    h, w = gray.shape[:2]
    x0, x1 = (int(col_cells.content_x[0]), int(col_cells.content_x[1])) if col_cells.content_x else (0, w)
    x0, x1 = max(0, x0), min(w, max(x1, x0 + 1))
    row = (gray[:, x0:x1] < ink_threshold).sum(axis=1) / (x1 - x0)
    near = FRAME_ONLY_NEAR * (col_cells.period or 1.0)
    out = []
    for c, border in ((cells[0], col_cells.border_top), (cells[-1], col_cells.border_bottom)):
        if c.kind == "blank" or border is None:
            continue
        a, b = max(0, int(c.y0)), min(h, int(c.y1))
        ys = np.nonzero(row[a:b] >= FRAME_ONLY_SPECK)[0] + a
        if len(ys) and np.abs(ys - border).max() <= near and row[ys].max() >= FRAME_ROW and c.slot not in out:
            out.append(c.slot)
    return out


# ── ②c 一页多列格位表回退（QTW 11-10 验收：表整页错一列时，错的列都打 layout_off／layout_unmerge 退回几何切，
#        格号不从墨来，②b 比格号集合抓不到）──────────────────────────────────────────

LAYOUT_FALLBACK_TAGS = ("layout_off", "layout_unmerge")
LAYOUT_FALLBACK_MIN = 2   # 一页这么多列退回才报


def layout_fallback_cols(page_cells) -> list[int]:
    """本页打了表回退旗（layout_off／layout_unmerge）的列号；不到 LAYOUT_FALLBACK_MIN 列返回空。"""
    cols = [cc.col for cc in page_cells.columns
            if any(str(f).startswith(LAYOUT_FALLBACK_TAGS) for f in (cc.flags or []))]
    return cols if len(cols) >= LAYOUT_FALLBACK_MIN else []


# ── ①b 外框到页边距离离群（QTW 11-10 验收：006 p153 右版框没印出，列网整体挪一列、末列落在版心条，
#        各列宽都正常，宽度比看不出）──────────────────────────────────────────────

MARGIN_DEV = 0.8          # 外框线到本页左／右边的距离，与本册同奇偶页的中位差 > 这么多列宽才报


def frame_margins(borders) -> dict | None:
    """一页边框结果 → {right, left, pitch}：最右、最左界行在版框中高处到页右、左边的距离（px）与中位列宽。

    边框坐标原点在页右上角、x 向左（`seg/frame_types`），所以 x 最小的是最右那条。
    `borders` 可以是产物 `Borders`（有 `to_result`）或 `BorderDetectionResult`。"""
    if hasattr(borders, "to_result"):
        borders = borders.to_result()
    v = getattr(borders, "verticals", None) or []
    if len(v) < 3:
        return None
    ym = (borders.top.y_at(borders.width / 2) + borders.bottom.y_at(borders.width / 2)) / 2
    xs = sorted(float(line.x_at(ym)) for line in v)
    return {"right": xs[0], "left": borders.width - xs[-1], "pitch": float(np.median(np.diff(xs)))}


def margin_outliers(margins: dict[int, dict]) -> list[dict]:
    """{页: frame_margins} → 离群页：左或右距离与同奇偶页中位差 > MARGIN_DEV × 中位列宽。"""
    out = []
    for parity in (0, 1):
        pages = {p: m for p, m in margins.items() if m and p % 2 == parity}
        if len(pages) < 5:
            continue
        med = {s: float(np.median([m[s] for m in pages.values()])) for s in ("left", "right")}
        pitch = float(np.median([m["pitch"] for m in pages.values()]))
        for p, m in sorted(pages.items()):
            dev = {s: m[s] - med[s] for s in ("left", "right")}
            side = max(dev, key=lambda s: abs(dev[s]))
            if abs(dev[side]) > MARGIN_DEV * pitch:
                out.append({"page": p, "side": side, "dev": round(dev[side] / pitch, 2),
                            "dist": round(m[side]), "median": round(med[side])})
    return out
