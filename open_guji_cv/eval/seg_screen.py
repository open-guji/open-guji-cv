"""切分筛查：只读产物与列图，各书通用，找出要看图的列与页（A22 F4①②、F7、F8，2026-11-10）。

设计：Claude Doc《切分框架改进详细设计（F1–F8）》F4 节；命令 `scripts/seg_screen.py`。
第一期只出报告，不进闸、不改产物；准了再把 ①② 升进 row_segment_gate／column_gate（第二期）。

| 项 | 名 | 判据 |
|---|---|---|
| ① | `edge_ink` | 列图上第一格之上、最后一格之下（版框以内），有墨行合计 > 0.5 格高（列首或列尾漏切） |
| ②a | `colnet_page` | 页内某正文列文字带宽 < 0.7 或 > 1.3 倍本页中位（整页列网错，常漏首列再劈出窄条） |
| ②b | `layout_col_shift` | 格位表列号整页挪 ±1 后对上的列明显更多（表把整页列号错了一列） |
| F7 | `pitch_free_ignored` | 表行写了 `pitch: free`，最后选中的格网却是挤格补线（`layout_unmerge`），pitch 没起作用 |
| ①c | `orphan` | 列中间整块墨不在任何字格里（先剥界行、版框长直线；判据照 SJ 快筛 ORPH，见 `orphan_ink`） |
| F8 | `seal_blank` | seed_admit 会按印框记空的格（`occlusion.page_seal_blank`），本机跑到 cell_shrink 就能看 |
| F6 | `cut_through` | 格线劈字：相邻两格的分界按连通块量切割量，在 ±0.4 格内挪能降到 1/4 以下、且 U-Net 归属裁判认挪后更对（`cut_through`，2026-11-13；要 torch） |
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


# ── ①c 漏切块（SJ 切分快筛 ORPH，11-11 搬进来）：列中间整块墨不在任何字格里，edge_ink 只看列端抓不到 ─────────────

ORPH_VLINE = 200          # 竖向开运算长度（px）：剥界行
ORPH_HLINE = 0.85         # 横向开运算长度（列宽倍数，至少 40px）：剥版框横线
ORPH_CLOSE = 9            # 闭运算核（px）：把一个字的散笔画连成一块
ORPH_FRAC = 0.25          # 块墨量 ≥ 本列字格墨量中位 × 这么多，
ORPH_MIN_PX = 150         # 且 ≥ 这么多像素才算一个字
ORPH_INSIDE = 0.2         # 块墨落在字格里的份额 ≤ 这么多才算漏切


def strip_long_lines(ink: np.ndarray) -> np.ndarray:
    """二值墨图（0/1）剥掉长直线：竖向开运算 ORPH_VLINE px（界行）、横向开运算 ORPH_HLINE 列宽（版框）。

    写本连笔加贯穿整列的界行，不剥的话一串字连成一块，连通块分析全错（SJ 快筛第二节）。实现在原语 `seg.rules`。"""
    from ..seg.rules import strip_long_rules
    return strip_long_rules(ink, vline=ORPH_VLINE, hline_frac=ORPH_HLINE, hline_min=40)


def orphan_ink(gray: np.ndarray, boxes, ink_threshold: int = 128) -> list[dict]:
    """一列列图 + 本列字格框（列图坐标 (x0, y0, x1, y1)，取 cell_shrink 判 char 的格）→ 漏切块
    `[{"bbox": [x0, y0, x1, y1], "ink": 像素, "ratio": 占字格中位, "where": head|mid|tail}]`。

    判据照 SJ `tools/seg_check/orphan.py`（r35／r41 史記十册验过）：剥长直线 → 闭运算 → 连通块；
    块内真墨 ≥ max(ORPH_MIN_PX, ORPH_FRAC × 字格墨中位)、落在字格里的 ≤ ORPH_INSIDE。排除：
    版框残带（高 ≤30 且宽 ≥半列或宽 ≥4×高）、粗版框黑带（宽 ≥0.8 列、高 ≤60、填充 ≥0.25）、
    版框折角（墨心贴列边 15% 内、填充 <0.3）、界行残段（宽 ≤25 且 ≤0.3×高）、稀疏框形（填充 <0.1）、
    网点霉斑（≥15 小块且块中位 <40px）、邻列字边（贴列图左／右边、只占边上 1/4 宽）。"""
    import cv2
    boxes = [tuple(int(round(v)) for v in b) for b in boxes]
    if not boxes:
        return []
    ink = strip_long_lines((gray < ink_threshold).astype(np.uint8))
    h, w = ink.shape
    blob = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((ORPH_CLOSE, ORPH_CLOSE), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(blob, connectivity=8)
    union = np.zeros_like(ink)
    inks = []
    for x0, y0, x1, y1 in boxes:
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        union[y0:y1, x0:x1] = 1
        inks.append(int(ink[y0:y1, x0:x1].sum()))
    med = float(np.median(inks))
    ytop, ybot = min(b[1] for b in boxes), max(b[3] for b in boxes)
    out = []
    for i in range(1, n):
        x, y, bw, bh, _a = (int(v) for v in st[i])
        m = (lab[y:y + bh, x:x + bw] == i) & (ink[y:y + bh, x:x + bw] > 0)
        real = int(m.sum())
        if real < ORPH_FRAC * med or real < ORPH_MIN_PX:
            continue
        if int((union[y:y + bh, x:x + bw] & m).sum()) > ORPH_INSIDE * real:
            continue
        fill = real / (bw * bh)
        if bh <= 30 and (bw >= 0.5 * w or bw >= 4 * bh):
            continue                                      # 版框残带
        if bw >= 0.8 * w and bh <= 60 and fill >= 0.25:
            continue                                      # 粗版框黑带（列尾整宽）
        cx = x + float(np.nonzero(m)[1].mean())
        if (cx >= 0.85 * w or cx <= 0.15 * w) and fill < 0.3:
            continue                                      # 版框折角
        if bw <= 0.3 * bh and bw <= 25:
            continue                                      # 界行残段
        if fill < 0.10:
            continue                                      # 稀疏框形
        k, _l, s2, _c = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        if k - 1 >= 15 and float(np.median(s2[1:, 4])) < 40:
            continue                                      # 网点／霉斑碎点
        if (x <= 1 and x + bw <= 0.25 * w) or (x + bw >= w - 1 and x >= 0.75 * w):
            continue                                      # 邻列字边
        where = "head" if y + bh <= ytop + 5 else "tail" if y >= ybot - 5 else "mid"
        out.append({"bbox": [x, y, x + bw, y + bh], "ink": real, "ratio": round(real / max(med, 1.0), 2),
                    "where": where})
    return out


# ── 史記切分快筛的格级判据（SJ `guji-manager/tools/seg_check`，2026-11-12 搬进来，《切分三方向》第 2 步） ─────
# 判据与参数照 SJ 原样（史記 r35／r41 十册验过）；SJ 要保留的几条见各函数说明。

LEDGER_MIN_PX = 8          # 连通块小于这么多像素不记账
LEDGER_SIDE = 0.15         # 贴列图左右边、占本格墨 < 这么多的小块：邻列字／界行残墨，不算
LEDGER_OWN = 0.35          # 别格为主的块占本格墨 > 这么多也算本格的（字身跨缝）
LEDGER_LINE_PX = 20        # 剥出来的长直线落进格框 ≥ 这么多像素才记 line
FOR_FRAC_LO, FOR_FRAC_HI, FOR_MIN_PX = 0.05, 1.5, 100   # FOR：别格墨占本格 5%–150% 且 ≥100px


def ink_ledger(gray: np.ndarray, cells, ink_threshold: int = 128) -> dict[str, dict]:
    """列图＋字格框墨账（SJ `ctx2.analyze_col`）：逐格量 own（本格字的墨）、foreign（别格的字墨进了本格框）、
    cut（本格字的墨落在所有框外）、line（剥出来的长直线落进框：('v'|'h', 像素)）。

    `cells`：[(id, (x0, y0, x1, y1), slot, sub)]，只给判字的格。先剥长直线（`seg.rules`，SJ 第 1 条：不剥的话写本连笔
    加界行整列连成一块）。夹注同号另半（a↔b）的墨不算 foreign（发前会抹白）。"""
    import cv2

    from ..seg.rules import horizontal_rule_mask, vertical_rule_mask
    raw = (gray < ink_threshold).astype(np.uint8)
    h, w = raw.shape
    vl, hl = vertical_rule_mask(raw), horizontal_rule_mask(raw)
    ink = ((raw > 0) & ~((vl | hl) > 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    boxes = []
    for _id, b, _s, _sub in cells:
        x0, y0, x1, y1 = (int(round(v)) for v in b)
        boxes.append((max(0, x0), max(0, y0), min(w, x1), min(h, y1)))
    comp_in: dict[int, dict[int, int]] = {}
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        sub = lab[y0:y1, x0:x1]
        ids, cnt = np.unique(sub[sub > 0], return_counts=True)
        for i, c in zip(ids, cnt):
            comp_in.setdefault(int(i), {})[k] = int(c)
    area = st[:, 4]
    union = np.zeros_like(ink)
    for x0, y0, x1, y1 in boxes:
        union[y0:y1, x0:x1] = 1
    outside = np.bincount(lab[(union == 0) & (ink > 0)].ravel(), minlength=n)
    owner = {i: max(ins.items(), key=lambda t: t[1])[0] for i, ins in comp_in.items()}
    out = {}
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        own = foreign = cut = side = 0
        pieces = [(i, ins[k]) for i, ins in comp_in.items() if k in ins and area[i] >= LEDGER_MIN_PX]
        box_ink = sum(c for _i, c in pieces)
        for i, c in pieces:
            x, _y, bw, _bh, _a = st[i]
            if owner[i] == k and (x <= 1 or x + bw >= w - 1) and c < LEDGER_SIDE * box_ink:
                side += c
                continue
            ok = owner[i]
            if ok == k or c > LEDGER_OWN * box_ink:
                own += c
                if ok == k:
                    cut += int(outside[i])
                continue
            if cells[ok][2] == cells[k][2] and (cells[ok][3] or "") != (cells[k][3] or ""):
                continue                                                   # 夹注同号另半
            foreign += c
        line = []
        lv, lh = int(vl[y0:y1, x0:x1].sum()), int(hl[y0:y1, x0:x1].sum())
        if lv >= LEDGER_LINE_PX:
            line.append(("v", lv))
        if lh >= LEDGER_LINE_PX:
            line.append(("h", lh))
        out[cells[k][0]] = {"own": own, "foreign": foreign, "cut": cut, "side": side, "line": line,
                            "fr": foreign / max(own, 1)}
    return out


def ledger_flags(rec: dict) -> list[str]:
    """墨账 → flags：FOR（别格墨进框）、Lh／Lv（长直线进框）。"""
    fl = []
    if any(t == "h" for t, _ in rec["line"]):
        fl.append("Lh")
    if any(t == "v" for t, _ in rec["line"]):
        fl.append("Lv")
    if rec["own"] > 0 and FOR_FRAC_LO <= rec["fr"] <= FOR_FRAC_HI and rec["foreign"] >= FOR_MIN_PX:
        fl.append("FOR")
    return fl


def end_frame_hits(gray: np.ndarray, boxes, border_top: float, border_bottom: float, *, ink_threshold: int = 128,
                   near: int = 4, cov: float = 0.45, band: int = 12) -> dict[int, list[tuple[str, float]]]:
    """列端版框（SJ `frame_end`，flag Fend）：格框伸到列图上／下版框线 `near` px 内，且格内贴该边 `band` 行里有一行墨
    覆盖 ≥ `cov` 格宽。返回 {格序号: [(top|bot, 覆盖)]}。"""
    ink = None
    out: dict[int, list] = {}
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        hit = [s for s, ok in (("top", y0 <= border_top + near), ("bot", y1 >= border_bottom - near)) if ok]
        if not hit:
            continue
        if ink is None:
            ink = gray < ink_threshold
        sub = ink[int(y0):int(y1), int(x0):int(x1)]
        if sub.size == 0:
            continue
        r = sub.mean(1)
        for s in hit:
            rr = r[:band] if s == "top" else r[-band:]
            if len(rr) and rr.max() >= cov:
                out.setdefault(k, []).append((s, float(rr.max())))
    return out


def _runs_max(v) -> int:
    best = cur = 0
    for x in v:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def patch_edge_lines(patch: np.ndarray, *, ink_threshold: int = 128, frac_w: float = 0.5, max_thick: float = 0.08,
                     min_gap: int = 2, gap_ink: float = 0.03) -> dict[str, dict]:
    """字块四边与字身隔开的薄直带（SJ `segqc.edge_lines`）：上下边的叫 Fpatch（版框／界栏横线），左右边的叫 Lv。
    带在边上 10% 内、厚 ≤ max(3, max_thick×边长)、与字身隔 ≥ min_gap 行空白、最长连续段 ≥ frac_w 宽。"""
    ink = patch < ink_threshold
    res = {}
    for side in ("top", "bot", "left", "right"):
        b = ink if side in ("top", "bot") else ink.T
        if side in ("bot", "right"):
            b = b[::-1]
        hh, ww = b.shape
        if hh == 0 or ww == 0:
            continue
        occ = b.sum(1) / ww > gap_ink
        if not occ.any():
            continue
        y0 = int(np.argmax(occ))
        if y0 > 0.1 * hh:
            continue
        y = y0
        while y < hh and occ[y]:
            y += 1
        y1 = y
        while y < hh and not occ[y]:
            y += 1
        gap = y - y1
        if y >= hh or gap < min_gap:
            continue
        thick = y1 - y0
        if thick > max(3, max_thick * hh):
            continue
        span = _runs_max(b[y0:y1].any(0)) / ww
        if span < frac_w:
            continue
        res[side] = {"thick": thick, "gap": gap, "span": span, "off": y0}
    return res


def jiazhu_wide(bbox, col_w: float, sub: str | None, frac: float = 0.7) -> bool:
    """夹注半格（a／b）框宽 ≥ 列宽 `frac`（SJ flag JZW：左右两字并一格）。"""
    return sub in ("a", "b") and (bbox[2] - bbox[0]) / max(col_w, 1.0) >= frac


def _slot_key(s: str):
    n = "".join(ch for ch in s if ch.isdigit() or ch == "-")
    try:
        return (int(n), s)
    except ValueError:
        return (0, s)


def pin_slots_diff(have: set[str], pin_cells) -> str:
    """钉子列（manual-cells）：cell_shrink 实出格号集合（"3"、"5a"…）对钉子格号集合，不一致返回说明，一致返回 ""。
    钉子列只比这个、不跑墨账判据（SJ 第 5 条）；slot 可以是 -1（按版式表抬头编号），照常比。"""
    want = {f"{c['slot']}{c.get('sub') or ''}" for c in pin_cells if c.get("kind", "char") != "blank"}
    miss, extra = sorted(want - have, key=_slot_key), sorted(have - want, key=_slot_key)
    if not (miss or extra):
        return ""
    return f"钉子有产物无 {','.join(miss) or '-'}；产物有钉子无 {','.join(extra) or '-'}"


def layout_slots_diff(have: set[str], row: dict) -> str | None:
    """版式对格号（SJ 第 4 条）：格位表一行（slots／notes／half）对实出格号。大字 N、小注 Na＋Nb、半格 Na（只切出 Nb
    也算对上）。对上 → None；格数相同只是编号不同（题署列大间距不留空位号）→ "同数"（判过、只计数）；格数不同 → 说明。"""
    notes, half = {int(x) for x in row.get("notes") or []}, {int(x) for x in row.get("half") or []}
    ids: set[str] = set()
    for n in row.get("slots") or []:
        n = int(n)
        ids |= {f"{n}a"} if n in half else {f"{n}a", f"{n}b"} if n in notes else {str(n)}
    halfa = {f"{n}a" for n in half}
    have = {h[:-1] + "a" if h.endswith("b") and h[:-1] + "a" in halfa and h[:-1] + "a" not in have else h for h in have}
    miss, extra = sorted(ids - have, key=_slot_key), sorted(have - ids, key=_slot_key)
    if not (miss or extra):
        return None
    if len(miss) == len(extra):
        return "同数"
    return f"异数：版式有产物无 {','.join(miss) or '-'}；产物有版式无 {','.join(extra) or '-'}"


# ── 并格／拆格：一列里格高离群（2026-11-12，召回尺子上发现的缺口） ──────────────────────────────

CELL_TALL = 1.7            # 格高 ≥ 本列有字格中位 × 这么多：多半两字并一格
CELL_SHORT = 0.5           # 格高 ≤ 本列中位 × 这么多：多半一字拆两格
CELL_MIN = 4               # 本列有字格少于这么多不查（中位不稳）


def odd_cell_heights(col_cells, *, tall: float = CELL_TALL, short: float = CELL_SHORT,
                     min_cells: int = CELL_MIN) -> list[dict]:
    """一列（row_segment 的 `ColumnCells`）里格高离群的格：[{slot, sub, ratio, kind: tall|short}]。

    殿本 vol01 职名页 ZM 11-12 钉的四列（88:1、88:4、88:6、105:4「講起」「閣領」两字一格）在旧包里格高都是本列中位的
    1.8–1.9 倍；整册 1724 列只有 6 列有 ≥1.7 倍的格，另两列（46:2、117:1）待看。"""
    cells = sorted((c for c in col_cells.cells if c.kind != "blank"), key=lambda c: c.y0)
    if len(cells) < min_cells:
        return []
    hs = sorted(c.y1 - c.y0 for c in cells)
    m = hs[len(hs) // 2] if len(hs) % 2 else (hs[len(hs) // 2 - 1] + hs[len(hs) // 2]) / 2
    if m <= 0:
        return []
    tight = _ink_tight(cells, m)
    out = []
    for i, c in enumerate(cells):
        r = (c.y1 - c.y0) / m
        if r <= short and tight is not None and _flat_glyph(cells, i, m, *tight, short=short):
            continue
        if r >= tall or r <= short:
            out.append({"slot": c.slot, "sub": c.sub, "ratio": round(r, 2), "kind": "tall" if r >= tall else "short"})
    return out


# 格贴墨切的列（职名、卷端题署走 roster，没有格网）：格高是字身高，扁字（一、二、三）本来就矮（史記 r61 卷端「史記卷一百一」的「一」
# 只有中位的 0.16–0.26，A22 11-14），要看它在列里站不站得住一个字的位置。史記 01／35／40 册 r61 这样的矮格 83 个，看图 79 个是
# 整字扁字；4 个真错：01:93:4:4、01:94:2:4（「二」上横并进上格「卷」，上格高 1.47–1.55 倍）、01:133:8:6、35:2:3:9（矮格是
# 残点／字的下半，离上格的留白只有中位的 0.63–0.77）。
TIGHT_GAP = 0.1            # 相邻有字格之间留白中位 ≥ 格高中位 × 这么多，且没有相叠的格＝格贴墨切
FLAT_PITCH = 0.5           # 矮格中心到上下邻格中心都 > 列中心距中位 × 这么多（一字拆两格，两半只隔半个字距）
FLAT_GAP = 0.9             # 矮格上下留白都 ≥ 列留白中位 × 这么多（残点、字的一截贴着邻字）
FLAT_NEIGHBOR = 1.35       # 上下邻格高都 < 格高中位 × 这么多（邻格吞了这个字的一笔，矮格只剩另一笔）


def _ink_tight(cells, m: float) -> tuple[float, float] | None:
    """格贴墨切的列返回 (相邻格中心距中位, 相邻格留白中位)，格网列（格与格相接）或有相叠格的列返回 None。"""
    if len(cells) < 2:
        return None
    gaps = sorted(b.y0 - a.y1 for a, b in zip(cells, cells[1:]))
    g = gaps[len(gaps) // 2]
    if gaps[0] < 0 or g < TIGHT_GAP * m:
        return None
    ds = sorted((b.y0 + b.y1 - a.y0 - a.y1) / 2 for a, b in zip(cells, cells[1:]))
    return ds[len(ds) // 2], g


def _flat_glyph(cells, i: int, m: float, pitch: float, gap: float, *, short: float = CELL_SHORT) -> bool:
    """贴墨列里第 i 个矮格是整字扁字：离上下字一个字距、上下留白不比别处窄、上下邻格高正常。"""
    c = cells[i]
    for j in (i - 1, i + 1):
        if not 0 <= j < len(cells):
            continue
        n = cells[j]
        if abs((n.y0 + n.y1) - (c.y0 + c.y1)) / 2 <= short * pitch:
            return False
        if (n.y0 - c.y1 if j > i else c.y0 - n.y1) < FLAT_GAP * gap:
            return False
        if (n.y1 - n.y0) >= FLAT_NEIGHBOR * m:
            return False
    return True


# ── 字块过高：Step4 字块比自己的格高出一大截（2026-11-13，殿本 vol06 147:3:3「也」，ZM） ────────────────

BLOCK_TALL = 1.35          # cell_shrink 字块高 ≥ 本格 row_segment 格高 × 这么多：字块连上了格外的墨（贯穿长竖线、印章、邻字）
BLOCK_MIN_EXTRA = 24       # 且比格高多出至少这么多像素（小格的取整误差不报）


def block_tall(block_h: float, cell_h: float, *, factor: float = BLOCK_TALL,
               min_extra: float = BLOCK_MIN_EXTRA) -> float | None:
    """字块高 ÷ 格高；不到 `factor` 倍或多出不到 `min_extra` 像素返回 None。

    cell_size、page_pitch 都比 row_segment 的**格线**高度，格线对而字块连上贯穿长竖线时（殿本 vol06 147:3:3「也」，
    格高 128、字块高 427，Step4 旗 boundary_ink）两者都不报；这里直接比字块。列末格（吃下面的空格位）由调用方不传。"""
    if cell_h <= 0 or block_h < factor * cell_h or block_h - cell_h < min_extra:
        return None
    return round(block_h / cell_h, 2)


# ── 整页均匀：正文格高、夹注半格宽（2026-11-12，Sheldon：除点名页外正文格高很均匀、双行小注宽度也均匀） ────────

PITCH_COL_DEV = 0.10       # 一列整字格高中位与本页中位差 > 这么多：整列格网缩放了（挤格／漏格／格网错位）
PITCH_TALL = 1.5           # 单格高 ≥ 本页格高中位 × 这么多：多半两字并一格（cell_size 只比本列，整列都歪时比不出）
PITCH_SHORT = 0.6          # 单格高 ≤ 本页中位 × 这么多：多半一字拆两格
PITCH_MIN_CELLS = 20       # 本页整字格少于这么多不判（职名页、书衣、空页）
PITCH_COL_MIN = 8          # 一列整字格少于这么多不比列中位（三五字的书名列格高本来就松，vol01/28 试跑全是这种误报）
HALF_LO, HALF_HI = 0.70, 1.40   # 夹注半格宽 ÷ 本册夹注半格宽中位，出这个范围报
HALF_PAIR = 0.30           # 同号 a/b 两半宽差 ÷ 两半宽和 > 这么多：中缝切偏了


def page_pitch(page_cells, skip_cols=()) -> float | None:
    """一页正文整字格（kind=char、无 sub、非职名列）格高中位；不到 PITCH_MIN_CELLS 格返回 None。"""
    hs = [c.y1 - c.y0 for cc in page_cells.columns if cc.ok and cc.col not in skip_cols and "roster" not in cc.flags
          for c in cc.cells if c.kind == "char" and c.sub is None]
    if len(hs) < PITCH_MIN_CELLS:
        return None
    hs.sort()
    return float(hs[len(hs) // 2])


def pitch_outliers(col_cells, pitch: float) -> dict | None:
    """一列对本页格高中位：列中位偏 > PITCH_COL_DEV，或有格 ≥ PITCH_TALL／≤ PITCH_SHORT 倍 → 
    {"col_ratio", "cells": [{slot, sub, ratio, kind}]}；都正常 → None。"""
    cells = [c for c in col_cells.cells if c.kind != "blank"]
    full = sorted(c.y1 - c.y0 for c in cells if c.sub is None and c.kind == "char")
    col_ratio = full[len(full) // 2] / pitch if len(full) >= PITCH_COL_MIN else 1.0
    odd = []
    for k, c in enumerate(cells):
        r = (c.y1 - c.y0) / pitch
        end = k == len(cells) - 1           # 列末字格吃掉下面的空格位（字块照样收墨），不算并格；cell_size 还会比本列
        if (c.sub is None and r >= PITCH_TALL and not end) or r <= PITCH_SHORT:
            odd.append({"slot": c.slot, "sub": c.sub, "ratio": round(r, 2), "kind": "tall" if r >= 1 else "short"})
    if abs(col_ratio - 1) <= PITCH_COL_DEV and not odd:
        return None
    return {"col_ratio": round(col_ratio, 3), "cells": odd}


def half_widths(col_cells) -> list[tuple[int, str, float]]:
    """一列夹注半格（a／b）的框宽 [(slot, sub, 宽 px)]。"""
    return [(c.slot, c.sub, c.x1 - c.x0) for c in col_cells.cells if c.sub in ("a", "b")]


def half_width_outliers(col_cells, median_w: float) -> list[dict]:
    """夹注半格宽对本册半格宽中位出 [HALF_LO, HALF_HI]，或同号 a/b 宽差 > HALF_PAIR → [{slot, sub, ratio|asym}]。"""
    out, by = [], {}
    for slot, sub, w in half_widths(col_cells):
        by.setdefault(slot, {})[sub] = w
        r = w / max(median_w, 1.0)
        if r < HALF_LO or r > HALF_HI:
            out.append({"slot": slot, "sub": sub, "ratio": round(r, 2)})
    for slot, d in by.items():
        if len(d) == 2:
            asym = abs(d["a"] - d["b"]) / max(d["a"] + d["b"], 1.0)
            if asym > HALF_PAIR:
                out.append({"slot": slot, "sub": "ab", "asym": round(asym, 2)})
    return out


# ── 参校字证实（2026-11-13，史記 R011／R013：写本扁字、大字、夹注半格宽差都是字形本来如此，格位与参校本一致） ──────

REF_OK_TOPK = 3            # 参校字落在本格字形匹配前这么多名里＝图像独立证实了这一格是这个字
REF_OK_COL = 0.85          # 整列格高偏（只有列中位偏、没有单格离群）时，本列有参校字的格 ≥ 这么多被证实（或只差 1 格）就不报


def ref_confirmed(glyph, aref, topk: int = REF_OK_TOPK) -> dict[tuple[int, int, str], bool | None]:
    """一页 {(列, 格号, sub): 证实与否}：align_ref 的参校字在 glyph_match 前 topk 名候选里 → True，不在 → False，
    这格没对上参校字 → None（无从证实，也不当反证）。

    只用字形匹配（只看图）当证据，不用 seed_admit 的放行字：follow_ref／match_ref 通道的放行字本来就抄参校字，拿它比参校字是循环论证。
    史記 r59（2 册、6 册）参校字落在前 3 名的格：整字 94%、夹注 93%。"""
    coord = {r.id: r.ref_char for r in (aref.coord if aref is not None else [])}
    out: dict = {}
    for cc in (glyph.columns if glyph is not None else []):
        for ch in cc.chars:
            rc = coord.get(ch.id)
            key = (cc.col, int(ch.slot), ch.sub or "")
            if not rc:
                out[key] = None
                continue
            out[key] = rc in [c[0] for c in (ch.candidates or [])[:topk]]
    return out


def ref_ok_cell(conf: dict, col: int, slot: int, sub: str | None) -> bool:
    """这一格被参校字证实，且上下邻格（同号 a/b 都算）没有反证：格高或半格宽离群但字对、前后也对＝写本字形本来如此，不是切错。
    真并格／拆格会把本格或邻格的字切坏、或让后面的格错一位，图上对不上参校字。sub＝"ab" 时 a、b 两半都要证实。"""
    subs = ["a", "b"] if sub == "ab" else [sub or ""]
    if not all(conf.get((col, slot, x)) for x in subs):
        return False
    for d in (-1, 1):
        if any(v is False for (c, s, _x), v in conf.items() if c == col and s == slot + d):
            return False
    return True


def ref_ok_col(conf: dict, col: int, frac: float = REF_OK_COL) -> bool:
    """本列有参校字的格大多被证实（≥ frac，或只差 1 格）：整列格网缩放了却字字对得上，多半是写本这一列字距本来疏密不同。"""
    vs = [v for (c, _s, _x), v in conf.items() if c == col and v is not None]
    if len(vs) < PITCH_COL_MIN:
        return False
    bad = sum(1 for v in vs if not v)
    return bad <= 1 or (len(vs) - bad) / len(vs) >= frac


# ── 对位串错·疑整列错位（2026-11-14，史記台账 R017，SJ 总览／切分线提） ──────────────────────────────────

DRIFT_RUN = 5              # 连续这么多格对不上参校字（B／b／n，其中有没放行的 b）：整列错一格
DRIFT_PAIR_TOTAL = 3       # 连续两格 b／n 之外，全列 b／n 还要 ≥ 这么多才报 pair（单处两格多是两个形近字挨着）
DRIFT_PAGE = 3             # 一页报出 ≥ 这么多列就是整页的事（透印、版式、对位整页没对上），降成提示
DRIFT_SKIP_TEXT = ("○", "考證")   # 考證页、考證列：整理本没有对应文字，格态全是 N／n，不查


def cell_states(adm_col, ref: dict, glyph: dict) -> str:
    """一列每格一个字母（按 seed_admit 的格序）：
    O 参校字在字形匹配前 3 名；B 有参校字、不在前 3 名、已放行；R 同上但走 rare_ref 放行（生僻字匹配本来就弱，不算串错）；
    N 没配到参校字、已放行；b／n 同 B／N 但没放行；o 对得上但没放行（不算串错证据）。
    `ref` 是 {格 id: 参校字}（align_ref 的 coord 加 ref_hint），`glyph` 是 {格 id: 字形匹配前 3 名（含 same 档的字）}。
    只用字形匹配当「对得上」的证据，不用放行字（follow_ref／match_ref 抄参校字）。"""
    out = []
    for x in adm_col.chars:
        r = ref.get(x.id)
        st = "N" if not r else ("O" if r in glyph.get(x.id, ()) else "B")
        if st == "B" and x.admit and x.channel == "rare_ref":
            st = "R"
        out.append(st if x.admit else st.lower())
    return "".join(out)


def align_drift(states: str, text: str = "", run: int = DRIFT_RUN) -> list[str]:
    """一列格态串（`cell_states`）里的整列错位迹象：
    - split：没配到参校字的格（n）挨着没放行的对不上格（b）——一个参校字跨两格（劈）；
    - pair：连续 ≥2 格没放行且对不上（b／n），全列这种格 ≥ DRIFT_PAIR_TOTAL——劈或并之后的那一段（有 split 只记 split）；
    - run：连续 ≥ run 格对不上（B／b／n）且其中有 b——整列错一格、放行器硬放了几格。
    放行字 `text` 含考證标记（○、考證）的列不查（参校本没这段，SJ 11-14 抽看第 1 条）。
    11-14 按 SJ 切分线抽看收紧（原版 run≥3／散在的 b≥3 也报，r59 报 172 列、看图 11 列全是识别认成形近字）：
    切分线 33 列仍报 23 列；r59 非钉子列 172→87，其中同页 ≥ DRIFT_PAGE 列的 12 列降成提示（见 seg_screen_run）；
    殿本 vol01／12／28／43 共 5,851 列 3→1。
    SJ 建议的「劈和并同时出现才报」「全 n／N 列不报」各会漏 12／2 列真错，没用；单格形近字误认（OOObbbOOO）
    与真劈并在格态上分不开，剩下的误报要靠看图。"""
    import re
    if any(t in text for t in DRIFT_SKIP_TEXT):
        return []
    hits = []
    if any(ch == "n" and "b" in (states[i - 1:i] + states[i + 1:i + 2]) for i, ch in enumerate(states)):
        hits.append("split")
    elif re.search("[bn]{2,}", states) and sum(ch in "bn" for ch in states) >= DRIFT_PAIR_TOTAL:
        hits.append("pair")
    if any(len(m.group(0)) >= run and "b" in m.group(0) for m in re.finditer("[Bbn]+", states)):
        hits.append("run")
    return hits


def page_ref_glyph(aref, glyph) -> tuple[dict, dict]:
    """一页 ({格 id: 参校字}, {格 id: 字形匹配前 3 名})。参校字取 align_ref 的 coord，再补 ref_hint（没有字形证据被筛掉的整理本字）。"""
    ref = {} if aref is None else {r.id: r.ref_char for r in aref.coord}
    for k, v in ((getattr(aref, "ref_hint", None) or {}) if aref is not None else {}).items():
        ref.setdefault(k, v)
    g = {}
    for cc in (glyph.columns if glyph is not None else []):
        for ch in cc.chars:
            g[ch.id] = ([ch.char] if ch.char else []) + [c[0] for c in (ch.candidates or [])[:REF_OK_TOPK]]
    return ref, g


# ── F6 格线劈字（2026-11-13，史記 r54 少见字页 SJ 量法，Sheldon 让 A22 并进 seg check） ────────────────

CUT_MID = 0.025            # 切割量 ≥ 格高² 的这么多才看（格高 110 约 300px，SJ「中档」下限）
CUT_STRONG = 0.066         # ≥ 格高² 的这么多算强档（格高 110 约 800px，SJ 强档抽 12 条看图 12 条真劈字）
CUT_REACH = 0.4            # 在名义格线 ±这么多格高内找切割量最小的行
CUT_SEP = 0.45             # 找的范围不越过相邻格线 ±这么多格高（同 row_boundaries.SNAP_CUT_MIN_SEP）
CUT_KEEP = 0.25           # 挪开处的切割量要 ≤ 原位这么多倍才算「挪得开」（两字粘连时人裁的线也带点墨：史記人裁尺子 58 条，0.1 只报出 23 条、0.25 报 33 条，准确率 86%→81%，A22 11-13）
CUT_WEAK_MOVE = 0.33       # 中档里挪不到这么多格高的记「弱」（seg check 只当提示）：史記 r59 20/37/41/42 册（A22 11-14）中档 67 条，
                           # 挪 <0.33 格高的 49 条只有 3 条在人后来钉的列里，且那 3 列另有强档／对位串错旗；≥0.33 的 18 条里 5 条是真劈
                           # （41:76:2、41:87:7 只有这一档）。挪得少＝原线已贴着字缝，多是上下字笔画相触（SJ 11-14 看图）
CUT_MOVE = 0.07            # 且要挪 ≥ 这么多格高（格高 110 约 8px，原位旁边几行就是缝的不报）
CUT_MAX_H = 1.6            # 纵向跨度超过这么多格高的连通块不算（界行残段、墨渍；同 row_boundaries.SNAP_CUT_MAX_H）
CUT_JUDGE = 0.09           # U-Net 归属裁判：挪后那条线的一致率比原位低不超过这么多才报。挪进字内白缝会把整块部件（之的捺、
                           # 忠的心、魯的日）划到邻格，一致率掉 ≥0.105；修钩尖、笔尾只动一小截，掉得少（史記 42 册 16 条 Sheldon 11-13 看图）


def _slot_spans(col_cells) -> list[dict]:
    """按格号合并（夹注 a/b 同格号算一格），按 y 排：[{slot, y0, y1, blank, seam_top, seam_bottom, x0}]。"""
    by: dict = {}
    for c in col_cells.cells:
        d = by.setdefault(c.slot, {"slot": c.slot, "y0": c.y0, "y1": c.y1, "blank": True,
                                   "seam_top": None, "seam_bottom": None, "x0": c.x0})
        d["y0"], d["y1"] = min(d["y0"], c.y0), max(d["y1"], c.y1)
        d["blank"] = d["blank"] and c.kind == "blank"
        if c.sub is None:
            d["seam_top"] = d["seam_top"] or c.seam_top
            d["seam_bottom"] = d["seam_bottom"] or c.seam_bottom
            d["x0"] = c.x0
    return sorted(by.values(), key=lambda d: d["y0"])


def _seam_ys(seam, sx0: int, x0: int, w: int) -> np.ndarray | None:
    """折线（列图坐标逐 x 的 y，从 `sx0` 起）换成内容窗 [x0, x0+w) 逐 x 的 y；窗内没有点返回 None，缺的 x 补中位数。"""
    ys = np.full(w, -1, dtype=np.int64)
    for i, y in enumerate(seam):
        x = sx0 + i - x0
        if 0 <= x < w:
            ys[x] = int(y)
    valid = ys >= 0
    if not valid.any():
        return None
    ys[~valid] = int(np.median(ys[valid]))
    return ys


def _seam_cut(lab: np.ndarray, keep: np.ndarray, areas: np.ndarray, ys: np.ndarray | None) -> float:
    """折线格线（`_seam_ys` 换好的逐 x 的 y）的切割量：Σ 跨线连通块 min(线上墨, 线下墨)。"""
    if ys is None:
        return 0.0
    h = lab.shape[0]
    above = np.arange(h)[:, None] < ys[None, :]
    up = np.bincount(lab[above & (lab > 0)], minlength=len(areas)).astype(np.float64)
    m = keep & (up > 0) & (up < areas)
    return float(np.minimum(up[m], areas[m] - up[m]).sum())


def cut_through(gray: np.ndarray, col_cells, ink_threshold: int = 128, *, mid: float = CUT_MID,
                strong: float = CUT_STRONG, judge=None) -> list[dict]:
    """一列里**劈字的格线**：[{slot_above, slot_below, y, cost, best, move, level: 强|中|弱}]（F6，2026-11-13）。

    相邻两格（夹注 a/b 合成一格看，两格都空的不看）的分界线，按连通块量切割量（Σ 被劈的连通块 min(线上墨, 线下墨)，
    `seg.seam.cut_cost_profile`；Step3 选了折线的按折线量）。切割量 ≥ `mid`×格高²、在 ±`CUT_REACH` 格高内（不越过相邻
    格线 `CUT_SEP` 格高）能挪到 ≤ 原位 `CUT_KEEP` 的行、且要挪 ≥ `CUT_MOVE` 格高，就报；切割量 ≥ `strong`×格高² 是强档，
    其余挪 ≥ `CUT_WEAK_MOVE` 格高的是中档、挪得更少的是弱档（只当提示，11-14）。

    逐格的「邻字残笔」FOR 分不开「笔尖伸进来」和「格线劈在字中间」（史記全书 FOR 约 15,700 格，r53 排查时当噪声放过）；
    这里量的是线本身劈了多少墨、挪开能不能避开：两字本来粘连的挪不开（最小处仍高），不报。
    挪开处还要过 U-Net 归属裁判（`judge`，`seg.cut_select.get_judge()`，同 snap_cut 整字护栏）：看上下两格整个窗口，挪后
    那条线的一致率比原位（有折线按折线）低不超过 `CUT_JUDGE` 才报。不过裁判时误报很多：殿本两字相粘处格线本来就对，最省墨处
    却在字内白缝（vol30 全册 33 条看图几乎全是这种，裁判后剩 5 条）。史記 42 册 9 页 16 条 Sheldon 11-13 看图：挪后更好 11、
    挪坏 5（之×2、帝、忠、魯，一致率都掉 ≥0.105）；门槛 0.09 报 9 条全对、挪坏的全拦，漏 2 条（掉 0.10、0.15）。`judge=None` 不过裁判（只给单测和诊断用）。
    史記 r53 SJ 离线：强档全书 1,170 条，抽 12 条看图 12 条真劈字；18 格人审劈字里 A 类 12 格抓到 11 格。"""
    from ..seg.seam import cut_cost_profile
    import cv2
    period = float(col_cells.period or 0.0)
    if period <= 0 or not col_cells.cells:
        return []
    h, w = gray.shape[:2]
    x0, x1 = (int(col_cells.content_x[0]), int(col_cells.content_x[1])) if col_cells.content_x else (0, w)
    x0, x1 = max(0, x0), min(w, max(x1, x0 + 1))
    ink = gray[:, x0:x1] < ink_threshold
    max_h = CUT_MAX_H * period
    prof = cut_cost_profile(ink, max_h=max_h)
    spans = _slot_spans(col_cells)
    if len(spans) < 2:
        return []
    lab = areas = keep = None
    p2 = period * period
    out = []
    for i in range(1, len(spans)):
        a, b = spans[i - 1], spans[i]
        if a["blank"] and b["blank"]:
            continue
        y = b["y0"]
        yi = int(round(min(max(y, 0.0), h)))
        seam = b["seam_top"] or a["seam_bottom"]
        ys0 = _seam_ys(seam, int(round(b["x0"] if b["seam_top"] else a["x0"])), x0, x1 - x0) if seam else None
        if ys0 is not None:
            if lab is None:
                n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
                areas = st[:, cv2.CC_STAT_AREA].astype(np.float64)
                keep = (st[:, cv2.CC_STAT_HEIGHT] >= 2) & (st[:, cv2.CC_STAT_HEIGHT] <= max_h)
                keep[0] = False
            c0 = _seam_cut(lab, keep, areas, ys0)
        else:
            c0 = float(prof[yi])
        if c0 < mid * p2:
            continue
        prev_y = a["y0"] if i >= 1 else 0.0
        next_y = b["y1"]
        lo = int(np.ceil(max(y - CUT_REACH * period, prev_y + CUT_SEP * period, 0)))
        hi = int(np.floor(min(y + CUT_REACH * period, next_y - CUT_SEP * period, h)))
        if hi < lo:
            continue
        k = int(np.argmin(prof[lo:hi + 1]))
        best = float(prof[lo + k])
        move = lo + k - y
        if best > CUT_KEEP * c0 or abs(move) < CUT_MOVE * period:
            continue
        agree = None
        if judge is not None:
            r = judge.assess(gray, x0, x1, int(round(a["y0"])), int(round(b["y1"])), float(y),
                             [ys0, np.full(x1 - x0, lo + k)], ink_threshold)
            if r is not None:
                agree = (r[0][0], r[0][1], r[1][0], r[1][1])
                if r[0][1] < r[0][0] - CUT_JUDGE:
                    continue
        out.append({"slot_above": a["slot"], "slot_below": b["slot"], "y": round(float(y), 1), "cost": int(c0),
                    "best": int(best), "move": int(round(move)), "level": "强" if c0 >= strong * p2 else "中" if abs(move) >= CUT_WEAK_MOVE * period else "弱",
                    "agree": agree})
    return out
