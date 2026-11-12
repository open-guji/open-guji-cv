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
    cells = [c for c in col_cells.cells if c.kind != "blank"]
    if len(cells) < min_cells:
        return []
    hs = sorted(c.y1 - c.y0 for c in cells)
    m = hs[len(hs) // 2] if len(hs) % 2 else (hs[len(hs) // 2 - 1] + hs[len(hs) // 2]) / 2
    if m <= 0:
        return []
    out = []
    for c in cells:
        r = (c.y1 - c.y0) / m
        if r >= tall or r <= short:
            out.append({"slot": c.slot, "sub": c.sub, "ratio": round(r, 2), "kind": "tall" if r >= tall else "short"})
    return out
