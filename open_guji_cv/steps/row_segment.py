"""Step3 单列文字切分：清理后列图 → 带类型的字格 + 读序。

包的是 `books/siku_zongmu/row_boundaries.segment_column`。输入参数全部来自交接闸（页级 period / ref_w，
列级 content_x / border_top / border_bottom / top_slack）；n_body_slots 来自 Book / 参数。
产物坐标是列图坐标，另带经 Step2 逆映射回原图的 quad_page（规范空间）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_serializer, model_validator

from ..core.book import _expand_pages
from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import CellRec, ColumnCells, CutPointCandidates, PageCells, SeamCandidate
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateManifest
from ..seg.cut_select import ckpt_fingerprint, get_judge
from ..books.siku_zongmu.row_grid import fit_page_grids
from ..books.siku_zongmu.row_boundaries import (NONUNIFORM_LAM, effective_body_slots,
                                    segment_column, slot_mask_from_occupied)
from ._warpmap import ColumnMapper

_LAYOUT_CACHE: dict[tuple, dict[tuple[int, int], dict]] = {}

#: layout_prior 的缺省表（中心库 corpus/daizhige/，`scripts/dzg_layout.py` 产出）；工作区里没有就当关。
DEFAULT_LAYOUT = "corpus/daizhige/layout_slots.jsonl"


def _layout_path(rel: str):
    """同 `_colgold_path`：``corpus/…`` 走数据目录（#198 起整理本进中心库）。"""
    return _colgold_path(rel)


def load_layout(rel: str, book: str) -> dict[tuple[int, int], dict]:
    """逐列格位表（`scripts/dzg_layout.py` 产出）→ 本册 {(页, 列): 行}。缓存按文件签名失效，同 `load_colgold`。"""
    import json
    p = _layout_path(rel)
    if not p.exists():
        raise FileNotFoundError(f"layout_prior 指的表不存在：{p}（先跑 scripts/dzg_layout.py）")
    key = (_sig(p), book)
    if key not in _LAYOUT_CACHE:
        out: dict[tuple[int, int], dict] = {}
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r.get("vol") == book:
                    out[(int(r["page"]), int(r["col"]))] = r
        _LAYOUT_CACHE[key] = out
    return _LAYOUT_CACHE[key]


def _layout_row(layout: dict, page: int, col: int) -> dict | None:
    """本列的格位表行。表里有这一页、但列号在这一页最后一列表行之后的，是卷末整列空的列（表只记有字的列），
    给一行「整列空」——印章、墨污落在这种列里也按表空格记空（殿本 vol04 p220、vol05 p188、vol06 p149）。"""
    row = layout.get((page, col))
    if row is not None:
        return row
    cols = [c for (pg, c) in layout if pg == page]
    if cols and col > max(cols):
        return {"slots": [], "notes": [], "half": [], "raised": 0}
    return None


#: 逐列字数先验一次最多改几个字（差得更多多半是列错位或页对错，硬改会把整列切乱）
COLGOLD_MAX_DIFF = 2
_COLGOLD_CACHE: dict[tuple, dict] = {}
_FP_CACHE: dict[tuple, str] = {}


def _sig(*paths) -> tuple:
    """文件签名（路径、mtime、大小）：进程内缓存按它失效——表或模型换了，长驻进程（控制台）也读新的。"""
    out = []
    for q in paths:
        st = q.stat()
        out.append((str(q), st.st_mtime_ns, st.st_size))
    return tuple(out)


def _colgold_path(rel: str):
    """相对路径按工作区解释；``corpus/…`` 走 ``corpus_path``（迁过中心库的工作区在数据目录）。"""
    from pathlib import Path
    from ..core.workspace import corpus_path, workspace_root
    p = Path(rel)
    if p.is_absolute():
        return p
    if len(p.parts) > 1 and p.parts[0] == "corpus":
        return corpus_path(str(Path(*p.parts[1:])))
    root = workspace_root()
    return (root / p) if root is not None else p


def load_colgold(rel: str, book: str) -> dict[tuple[int, int], dict]:
    """逐列字数表 → {(页, 列): 行}，只收本册、双源一致（`agree`）、无夹注且有 `start` 的列。

    `start` 为空（整理本不录行首留白）的不收：计数的格位段要靠它定，按 0 算会把缩进列的末字划到段外
    （另一分支用光盘版表实测，vol04 坏 232 列）。"""
    import json
    p = _colgold_path(rel)
    if not p.exists():
        raise FileNotFoundError(f"colgold_prior 指的表不存在：{p}（先跑 scripts/dzg_import.py colgold）")
    key = (_sig(p), book)
    if key not in _COLGOLD_CACHE:
        out = {}
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if (r.get("vol") == book and r.get("agree") and not r["dzg"].get("note")
                    and r["dzg"].get("start") is not None):
                out[(int(r["page"]), int(r["col"]))] = r
        _COLGOLD_CACHE[key] = out
    return _COLGOLD_CACHE[key]


def apply_count_target(r, seg, n_body: int, want: int, tag: str,
                       max_diff: int = COLGOLD_MAX_DIFF, count=None):
    """按目标字数重切一列：`seg(n_body)` 是本列的 DP 调用，`r` 是按 `n_body` 切出的结果。

    切出字数 ≠ `want` 且差 ≤ `max_diff` → 格数减去差值重切一次；重切后字数**恰好**等于 `want` 才采用。
    含夹注的列不碰（夹注两小字占一格，字数换格数不是简单相减）。
    `count(cells)` 给「这一列算几个字」，缺省数非空格（`_n_chars`）。
    返回 (结果, 采用的格数, 旗)；旗以 `<tag>_prior` / `<tag>_conflict` 开头。"""
    count = count or _n_chars
    if r is None or _has_jiazhu(r.cells):
        return r, n_body, []
    got = count(r.cells)
    d = got - want
    if d == 0:
        return r, n_body, []
    if abs(d) > max_diff:
        return r, n_body, [f"{tag}_conflict：切出 {got} 字，目标 {want}，差 {d} 超过 {max_diff} 不套"]
    r2 = seg(n_body - d)
    if r2 is not None and count(r2.cells) == want and not _has_jiazhu(r2.cells):
        return r2, n_body - d, [f"{tag}_prior：字数 {got}→{want}（格数 {n_body}→{n_body - d}）"]
    return r, n_body, [f"{tag}_conflict：切出 {got} 字，目标 {want}，按差值重切仍对不上"]


_YOLO_CACHE: dict[tuple, object] = {}


def _yolo(model_dir: str):
    from ..books.siku_zongmu.yolo_tool_infer import YoloTool
    d = _colgold_path(model_dir)
    key = _sig(d / "type" / "best.onnx", d / "slide" / "best.onnx")
    if key not in _YOLO_CACHE:
        _YOLO_CACHE[key] = YoloTool(d)
    return _YOLO_CACHE[key]


def _cover(box, y) -> float:
    iw = min(box[2], y[2]) - max(box[0], y[0])
    ih = min(box[3], y[3]) - max(box[1], y[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    return iw * ih / max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))


def yolo_merge_pairs(ink_boxes: list, yolo_boxes: list, cover: float = 0.6, max_h: float = 1.3) -> int:
    """同列按读序排好的正文字格墨迹框（左上原点页坐标，`None` = 空格）× 本页 YOLO 字框 → 「一字两格」对数。

    `yolo_boxes` 已按置信度筛过；框高超过本页中位 `max_h` 倍的不用——YOLO 偶尔把两个字并成一个
    约两倍高的框，那种框会把两个真字误报成一对（研究文档 §四-4′：不加这条 100 页误报 7，加了 0）。
    一个格只配一对（配上之后跳过下一格）。"""
    if not yolo_boxes:
        return 0
    hs = sorted(b[3] - b[1] for b in yolo_boxes)
    mh = hs[len(hs) // 2]
    ys = [b for b in yolo_boxes if b[3] - b[1] <= max_h * mh]
    k, i = 0, 0
    while i + 1 < len(ink_boxes):
        a, b = ink_boxes[i], ink_boxes[i + 1]
        if a is not None and b is not None and any(_cover(a, y) >= cover and _cover(b, y) >= cover for y in ys):
            k += 1
            i += 2
        else:
            i += 1
    return k


def _ink_box(img, c, thr: int):
    """列图里一格的墨迹外接框（列图坐标）；格里没墨返回 None。"""
    import numpy as np
    y0, y1 = max(0, int(c.y0)), min(img.shape[0], int(round(c.y1)))
    x0, x1 = max(0, int(c.x0)), min(img.shape[1], int(round(c.x1)))
    if y1 <= y0 or x1 <= x0:
        return None
    m = img[y0:y1, x0:x1] < thr
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return (x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1)


#: 金标说这一格该空、Step3 却给了 char 的格，墨占比低于此就不算字——那是列首/列尾残墨
#: （抬头位残框、虚线），Step4 会按 `tail_junk` 丢掉；按 Step3 原样计数会把本来对的列
#: 「纠」成少一字（vol04 抽 50 页首版实测：修好 2、改坏 47）。阈值在测试 B 100 页上量的：
#: 0.08 时「Step3 计数判错、Step4 其实对」只 1 列，判对 15、漏 5（doc/design/19 变更记录）。
COLGOLD_JUNK_INK = 0.08


#: 金标字段之外的格要有「字证据」才算字（判据与阈值照 Step4 列端渣格闸 `is_end_cell_junk`
#: 的主干，`clustering/extractor.py` 的 TAIL_JUNK_*，不 import 是免得它进 Step3 指纹）：
#: 满宽且矮的是框线条渣、碎点不算；剩下的连通体有一个够高、或合起来纵跨够长（「二/三」）就是字。
#: vol06 p40：上框线落在首字前一格、墨 0.11 → 不算；vol04 p12 c7：D 并好的「三」→ 算。
COLGOLD_BAR_W = 0.92
COLGOLD_BAR_H = 0.35
COLGOLD_MIN_AREA = 60
COLGOLD_CC_H = 0.30
COLGOLD_SPAN = 0.35


def _looks_like_char(img, c, thr: int) -> bool:
    import cv2
    import numpy as np
    y0, y1 = max(0, int(c.y0)), min(img.shape[0], int(round(c.y1)))
    x0, x1 = max(0, int(c.x0)), min(img.shape[1], int(round(c.x1)))
    if y1 <= y0 or x1 <= x0:
        return False
    H, W = y1 - y0, x1 - x0
    n, _lab, st, _c = cv2.connectedComponentsWithStats((img[y0:y1, x0:x1] < thr).astype(np.uint8), 8)
    top = bot = None
    for k in range(1, n):
        y, w, h, area = int(st[k, 1]), int(st[k, 2]), int(st[k, 3]), int(st[k, 4])
        if w >= COLGOLD_BAR_W * W and h < COLGOLD_BAR_H * H:
            continue                      # 满宽且矮：框线
        if area < COLGOLD_MIN_AREA or h < 4:
            continue                      # 碎点
        if h >= COLGOLD_CC_H * H:
            return True
        top = y if top is None else min(top, y)
        bot = y + h if bot is None else max(bot, y + h)
    return top is not None and bot - top >= COLGOLD_SPAN * H


def colgold_count(g: dict, img=None, thr: int = 128):
    """按金标格位计数：格位在金标字段（start+1 … start+n）里的非空格都算；之外的只算墨够、
    与金标字段之间没有空格隔开（隔着空格的列端孤格是残墨，Step4 会按 `tail_junk` 丢掉）、
    且（给了列图时）有整字级连通体的（版框横线不算）。"""
    start = int(g["start"] or 0)
    lo, hi = (start if start < 0 else start + 1), start + int(g["n"])   # start < 0 = 抬头字，占 start…-1 格，后接 1 号格

    def out_ok(c) -> bool:
        return c.ink_ratio >= COLGOLD_JUNK_INK and (img is None or _looks_like_char(img, c, thr))

    def count(cells) -> int:
        # 按格的先后往两端走（格位号不连续：抬头位 -1 后面直接是 1），遇到空格就停
        seq = sorted(cells, key=lambda c: c.slot)
        idx = [i for i, c in enumerate(seq) if lo <= c.slot <= hi]
        n = sum(1 for i in idx if seq[i].kind != "blank")
        if not idx:
            return n + sum(1 for c in seq if c.kind != "blank" and out_ok(c))
        for rng in (range(idx[-1] + 1, len(seq)), range(idx[0] - 1, -1, -1)):
            for i in rng:
                if seq[i].kind == "blank":
                    break
                n += out_ok(seq[i])
        return n
    return count


def _layout_kw(lay: dict, occ: set, n_body: int, n_raised: int):
    """逐列格位表的一行 → (segment_column 参数, forced_jiazhu, forced_main)。两半都有字的夹注格强制拆、正文格强制整，
    只有一半有字的夹注格（half）只发墨多的一半。"""
    notes = set(lay.get("notes", ())) & occ
    half = set(lay.get("half", ())) & occ
    return ({"slot_mask": slot_mask_from_occupied(occ, n_body, n_raised), "half_notes": half or None},
            notes or None, (occ - notes - set(lay.get("half", ()))) or None)


#: 格线穿字判据：格线上下 ±2 行、列宽中间 80% 的墨占比都 ≥ 这个值，算这条线横穿了字
CUT_ROW_INK = 0.06


def _cut_rows(img, cells, ink_threshold: int = 128) -> int:
    """一列里横穿字的格线条数（字格与相邻格的分界；空格之间、夹注 a/b 之间不算）。只用来比两种格网谁劈字少。"""
    import numpy as np
    h, w = img.shape[:2]
    g = img if img.ndim == 2 else img.mean(axis=2)
    ink = (g[:, int(w * 0.1):int(w * 0.9)] < ink_threshold).mean(axis=1)
    cs = sorted(cells, key=lambda c: c.y0)
    n = 0
    for a, b in zip(cs, cs[1:]):
        if (a.kind == "blank" and b.kind == "blank") or (a.sub and b.sub and a.slot == b.slot):
            continue
        y = int(round(b.y0))
        if 2 <= y < h - 2 and float(np.min(ink[y - 2:y + 3])) >= CUT_ROW_INK:
            n += 1
    return n


#: 列端框线残渣判据：像字的墨行（行墨 ≥ 0.08 列宽且 < 0.5 列宽，同 row_boundaries 的空白格口径）
#: 合起来不到这么多个 period，且满宽横线（±3 行）以外的墨占格面积不到 FRAME_JUNK_RESID，就当这一格没有字
FRAME_JUNK_CHARLIKE = 0.15
FRAME_JUNK_RESID = 0.03


#: 越界墨判据：格里有墨的行中，墨伸到内容窗口左右两侧 EDGE_BAND 列宽以内的行占到 EDGE_ROWS 以上，算越过了界行。
#: 字守在本列界行之内（殿本 vol05/vol09 七千多个字格：95% 分位 0.01、99.9% 分位 0.3）；跨好几列的印章、
#: 整片墨污才伸到列边上（表空格里的这类墨中位 0.39）
EDGE_BAND = 0.06
EDGE_ROWS = 0.35

#: 碎墨判据：格里的墨落在大连通块（面积 > STROKE_AREA 像素，同 occlusion.OCC_AREA_MAX，字的笔画主体）里的比例
#: 不到 STROKE_FRAC，算不像字。字的墨几乎都连成笔画（殿本 vol04/vol09 七万三千个表认下的字格：0.1% 分位 0.75，
#: 中位 1.0）；印章的印泥斑点、篆文残笔是成片的小墨点（vol04 p3 印章压着的表空格 0~0.69）
STROKE_AREA = 150
STROKE_FRAC = 0.75
#: 竖线判据：格里有墨的像素列（一列至少 2 个墨点）不到内容宽的 VLINE_COLS，墨只是一两道竖线（印框的边、界行残段），
#: 不是字——再窄的字也横跨大半格宽（殿本 vol04 p127 c7、vol05 p188 c7：印框左右边落在列端表空格里）
VLINE_COLS = 0.2


def _edge_rows(ink) -> float:
    """格内（二值）墨伸到左右侧边的行数 ÷ 有墨的行数。"""
    w = ink.shape[1]
    e = max(2, int(w * EDGE_BAND))
    rows = int(ink.any(axis=1).sum())
    if rows == 0:
        return 0.0
    return float((ink[:, :e].any(axis=1) | ink[:, -e:].any(axis=1)).sum()) / rows


def _stroke_mask(ink):
    """（二值）墨里属于大连通块（笔画）的像素。"""
    import cv2
    _n, lab, st, _c = cv2.connectedComponentsWithStats(ink.astype("uint8"), connectivity=8)
    big = st[:, cv2.CC_STAT_AREA] > STROKE_AREA
    big[0] = False
    return big[lab]


def _blank_frame_junk(img, cells, occ: set, content_x, ink_threshold: int, period: float, in_seal=None) -> int:
    """表说该空、又在表的首字之前或末字之后（列端那一段表空格；表说整列空就是整列）的非空格（字、單行小注、雙行小注的半格都算），
    里面的墨不像字就改成 blank，返回改了几格。不像字 = 只有框线／零星碎点，或者墨越过了界行（印章、墨污，见
    EDGE_ROWS），或者墨大多是碎点、连不成笔画（印章，见 STROKE_FRAC），或者墨只是一两道竖线（见 VLINE_COLS），或者格一半以上落在印框里（`in_seal(cell)`，
    印来自印章定位 `seals`，见 `_in_seal`）。"""
    import numpy as np
    body = sorted(occ)
    lo, hi = (body[0], body[-1]) if body else (1, 0)
    h, w = img.shape[:2]
    g = img if img.ndim == 2 else img.mean(axis=2)
    x0, x1 = (int(content_x[0]), int(content_x[1])) if content_x else (0, w)
    x0, x1 = max(0, x0), min(w, max(x1, x0 + 1))
    cw = x1 - x0
    ink = g[:, x0:x1] < ink_threshold
    stroke = _stroke_mask(ink)
    row = ink.sum(axis=1)
    charlike = (row >= 0.08 * cw) & (row < 0.5 * cw)
    frame = row >= 0.5 * cw
    near = frame.copy()
    for d in (1, 2, 3):
        near[d:] |= frame[:-d]
        near[:-d] |= frame[d:]
    order = sorted(cells, key=lambda c: c.y0)
    n = 0
    for c in order:
        if c.kind == "blank" or lo <= c.slot <= hi or c.slot in occ:
            continue
        a, b = max(0, int(c.y0)), min(h, int(c.y1))
        if b <= a:
            continue
        if in_seal is not None and in_seal(c):
            c.kind = "blank"
            n += 1
            continue
        resid = float(ink[a:b][~near[a:b]].sum()) / ((b - a) * cw)
        frame_only = charlike[a:b].sum() < FRAME_JUNK_CHARLIKE * period and resid < FRAME_JUNK_RESID
        n_ink = int(ink[a:b].sum())
        speckle = n_ink > 0 and stroke[a:b].sum() < STROKE_FRAC * n_ink
        vline = n_ink > 0 and int((ink[a:b].sum(axis=0) >= 2).sum()) < VLINE_COLS * cw
        if frame_only or speckle or vline or _edge_rows(ink[a:b]) >= EDGE_ROWS:
            c.kind = "blank"
            n += 1
    return n


#: 格落在印里的两种量法（印来自印章定位 `seals` 产物，见 `_page_seals`）：大印——格与印框重叠 ≥ SEAL_OVERLAP；
#: 小印——格里 ≥ SEAL_STROKE 的墨属于压着印笔画覆盖区（`seal_detect.stroke_mask`）的连通块。小印按笔画量而不按框：
#: 印边只盖住一列的一小半时，那一列表空格里的墨仍是印（殿本 vol06 p149 c7）。
SEAL_OVERLAP, SEAL_STROKE = 0.5, 0.7
#: 大印下的列：等距格网在印外比按打分挑出的格网多劈这么多个字，就不硬取等距格网（1.41）
STAIN_GRID_MARGIN = 2


def _page_seals(ctx, page: int) -> list[tuple]:
    """本页的印 [(规范空间印框 x0, y0, x1, y1, 小印笔画掩码或 None)]，掩码是左上原点整页的；读不到产物就是空表。"""
    from .seal_detect import stroke_mask
    if not ctx.has_product("seals", page):
        return []
    ps = ctx.product("seals", page)
    return [(*s.bbox, stroke_mask(s, ps.height, ps.width)) for s in ps.seals]


def _in_seal(seals, mapper, img=None, ink_threshold: int = 128):
    """格（列图坐标）落在某方印里的判定函数（量法见 SEAL_OVERLAP／SEAL_STROKE）；没有印或列图映射时为 None。
    `img` 是这一列的列图（界行、版框已清掉），量小印笔画时取格里的墨点映回原图去对掩码；不给就只按框量。"""
    import numpy as np
    if not seals or mapper is None:
        return None
    g = None if img is None else (img if img.ndim == 2 else img.mean(axis=2))

    def on_strokes(c, mask) -> bool:
        """格里的墨按连通块算：块里有墨点映回原图落在笔画覆盖区上，整块都算印（每次钤盖跟模板对不严，
        印边的一笔常只有一半压在覆盖区里，vol06 p149 c7）。"""
        import cv2
        a = int(c.y0)
        ink = (g[a:int(c.y1)] < ink_threshold).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        total = int(st[1:, 4].sum()) if n > 1 else 0
        if total == 0:
            return False
        H, W = mask.shape
        seal = 0
        for i in range(1, n):
            ys, xs = np.nonzero(lab == i)
            k = max(1, len(ys) // 50)               # 每块最多量 50 个墨点
            for x, y in zip(xs[::k], ys[::k]):
                X, Y = mapper.to_page_tl(float(x), float(y) + a)
                if 0 <= int(Y) < H and 0 <= int(X) < W and mask[int(Y), int(X)] > 0:
                    seal += int(st[i, 4])
                    break
        return seal >= SEAL_STROKE * total

    def f(c) -> bool:
        q = mapper.quad_tr(c.x0, c.y0, c.x1, c.y1)
        xs, ys = [x for x, _ in q], [y for _, y in q]
        gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
        area = (gx1 - gx0) * (gy1 - gy0)
        if area <= 0:
            return False
        for bx0, by0, bx1, by1, mask in seals:
            ix = max(0.0, min(gx1, bx1) - max(gx0, bx0))
            iy = max(0.0, min(gy1, by1) - max(gy0, by0))
            if ix * iy <= 0:
                continue
            if mask is None or g is None:
                if ix * iy / area >= SEAL_OVERLAP:
                    return True
            elif on_strokes(c, mask):
                return True
        return False
    return f



def _under_stain(seals, mapper, content_x, border_top: float, period: float) -> bool:
    """这一列的首格（版框顶下一格）一半以上压在大印（`seals` 里没有笔画掩码的那种）下。"""
    q = mapper.quad_tr(float(content_x[0]), float(border_top), float(content_x[1]), float(border_top) + period)
    xs, ys = [x for x, _ in q], [y for _, y in q]
    gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
    area = (gx1 - gx0) * (gy1 - gy0)
    for bx0, by0, bx1, by1, mask in seals:
        if mask is None and area > 0:
            ix = max(0.0, min(gx1, bx1) - max(gx0, bx0))
            iy = max(0.0, min(gy1, by1) - max(gy0, by0))
            if ix * iy / area >= SEAL_OVERLAP:
                return True
    return False

#: 劈字判据：一个连通体高在 [SPLIT_CC_MIN, SPLIT_CC_MAX] 个 period 之间（像一个字，不是碎点、不是界行），
#: 格线从中间穿过、上下两段都占它高的 SPLIT_SIDE 以上，算这条格线把字劈了
SPLIT_CC_MIN, SPLIT_CC_MAX, SPLIT_SIDE = 0.3, 1.5, 0.3


def _split_chars(img, cells, period: float, ink_threshold: int = 128) -> int:
    """一列里把单个连通体（一个字）从中间劈开的格线条数。比 _cut_rows 稳：只看行墨的判据会被
    稀疏笔画骗过（「疏」「僅」被劈也只穿过一两笔），看连通体则一个字被劈就是被劈。"""
    import cv2
    import numpy as np
    g = img if img.ndim == 2 else img.mean(axis=2)
    h, w = g.shape[:2]
    binary = (g[:, int(w * 0.1):int(w * 0.9)] < ink_threshold).astype(np.uint8)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    ccs = [(int(st[k, 1]), int(st[k, 1] + st[k, 3])) for k in range(1, n)
           if SPLIT_CC_MIN * period <= st[k, 3] <= SPLIT_CC_MAX * period]
    cs = sorted(cells, key=lambda c: c.y0)
    k = 0
    for a, b in zip(cs, cs[1:]):
        if (a.kind == "blank" and b.kind == "blank") or (a.sub and b.sub and a.slot == b.slot):
            continue
        y = b.y0
        k += any(y - t >= SPLIT_SIDE * (e - t) and e - y >= SPLIT_SIDE * (e - t) for t, e in ccs)
    return k


#: 挤格判据：一个字格的墨高超过 MERGE_INK_H 个 period，且中间有一整行白缝把墨分成上下两段、
#: 两段都高过 MERGE_PART_H 个 period——两个字挤进了一格（不是列端字带进的框线：框线那段矮）。
#: 一列最多补 MERGE_MAX_FIX 次
MERGE_INK_H, MERGE_PART_H, MERGE_MAX_FIX = 1.25, 0.4, 3


def _merged_cuts(img, cells, period: float, ink_threshold: int = 128) -> list[float]:
    """一列里挤着两个字的字格，各给一条该补的格线（列图 y，取离墨中点最近的那道白缝的中线）。殿本个别列字排得比
    整页格网密（挖改处多刻一字等），照格网切会把两个字塞进一格，_split_chars 看不见（没有劈开哪个连通体）。"""
    import numpy as np
    g = img if img.ndim == 2 else img.mean(axis=2)
    w = g.shape[1]
    out = []
    for c in cells:
        if c.kind == "blank" or c.sub:
            continue
        y0, y1 = max(0, int(c.y0)), min(g.shape[0], int(round(c.y1)))
        rows = (g[y0:y1, int(w * 0.1):int(w * 0.9)] < ink_threshold).any(axis=1)
        ys = np.nonzero(rows)[0]
        if len(ys) == 0 or ys[-1] - ys[0] < MERGE_INK_H * period:
            continue
        mid = (ys[0] + ys[-1]) / 2
        runs = np.split(ys, np.nonzero(np.diff(ys) > 1)[0] + 1)
        gaps = [(runs[i - 1][-1] + runs[i][0]) / 2 for i in range(1, len(runs))
                if runs[i - 1][-1] - ys[0] >= MERGE_PART_H * period and ys[-1] - runs[i][0] >= MERGE_PART_H * period]
        if gaps:
            out.append(y0 + min(gaps, key=lambda y: abs(y - mid)))
    return out


#: 格高不匀：字格（缩框前）的高偏离 period 超过这个比例。殿本格高均匀，「一」「二」这类矮字在 Step3 也占满一格，
#: 到 Step4 缩框才变矮；一格明显偏高或偏矮，多半是格线落错了缝（用户 2026-10-25）
UNEVEN_TOL = 0.3


def _uneven(cells, period: float) -> int:
    """格高不匀的字格数（只数正文整格；空白格、夹注半格不算）。"""
    return sum(1 for c in cells if c.kind == "char" and abs((c.y1 - c.y0) / period - 1) > UNEVEN_TOL)


def _mask_misses(cells, occ: set) -> int:
    """一种格网违表的格数：表说有字却切成空、表说该空却切出字。掩码是软约束，DP 为躲穿字会违表。"""
    got = {c.slot for c in cells if c.kind != "blank"}
    return len(got ^ set(occ))


def _n_chars(cells) -> int:
    return sum(1 for c in cells if c.kind != "blank")


def _has_jiazhu(cells) -> bool:
    return any(c.kind.startswith("jiazhu") for c in cells)


class RowSegmentParams(BaseModel):
    n_body_slots: int | None = None      # None = Book.chars_per_line
    n_raised: int = 0                    # 抬头多出的格数；版式先验，raised 不自动推
    ink_threshold: int = 128
    min_ink_ratio: float = 0.01
    raise_tol: float = 2.0
    detect_jiazhu: bool = True
    only_admitted: bool = True           # 只切过闸的列
    seam_band: int = 20                  # 折线切分走廊半宽；0 = 关（seg/seam.py）
    cut_judge: str = "unet"              # 候选池裁判：unet（seg/cut_select.py，2026-09-14 起现役）| rule（只用旧规则）
    judge_fingerprint: str = ""          # 裁判权重指纹，自动填（进 Step 指纹：换权重 → Step3 产物自动 stale）
    detect_bottom_bar: bool = True       # 列里还躺着下版框线时下界改用它（row_boundaries.find_bottom_frame_bar）
    #: **职名页分支**（overview#450，S4，2026-10-06）：列在这里的页不走固定格数 DP，改走
    #: `books/siku_zongmu/roster_segment`（不定字数、二维递归切）。默认空 = 关，别的书别的页产物逐字节不变。
    #: 只在册配置里点名开（`params: {row_segment: {roster_pages: ["89-132"]}}`），不自动判页型——
    #: 闸1 判不出职名页（见 row_segment_gate 模块头 L0u 一节），点名是人定的。
    roster_pages: list[int | str] = []
    #: **列端虚线残段记空白**（overview#376 后续，2026-10-07）：缺省关，关时产物逐字节不变。开了以后，
    #: 首格/末格/抬头格里墨的外接框竖向 ≤ `dash_h_frac`×period 且横向 ≤ `dash_w_frac`×列宽的，kind 记 `blank`
    #: 而不是没字的 `char`。阈值未经真图标定（云端没有原图），先按 S2 实测「虚线跨度 ≤29 行 ≈ 0.25 period」取。
    dash_blank: bool = False
    dash_h_frac: float = 0.3
    dash_w_frac: float = 0.25
    #: 职名页密排段**按本书字形库重切**（overview#450，2026-10-07，`books/siku_zongmu/roster_glyph`）：
    #: 压扁粘连字几何上数不准字数，拿库里刻例比相似度定切法。默认关；开了才读库、才填指纹。
    roster_glyph_refine: bool = False
    roster_glyph_db: str = ""            # 空 = 工作区 output/glyph.db（core.workspace.glyph_db_path）
    roster_glyph_fingerprint: str = ""   # 库内容指纹，开关开着时自动填；soft：库变只记漂移不判过期（同 glyph_match）
    #: 职名页按整理本字数重切（史記文淵閣本，`books/shiji_wyg/roster_segment.refit_column`）：殆知阁源记录目录
    #: （放 0243.jsonl 等，如 `daizhige`）与页钉位表（语料目录下的名字，同 align_ref.page_pins）。两个都给才开；只有实现了 `page_ref_lines` 的套书用得上，
    #: 殿本的职名页实现不认，关时产物逐字节不变。
    roster_ref_corpus: str = ""
    roster_ref_pins: str = ""
    roster_ref_fingerprint: str = ""     # 两个文件的内容指纹，开着时自动填
    #: **逐列字数先验**（doc/design/19 块 C，2026-10-19）：工作区里的逐列字数金标表
    #: （`scripts/dzg_import.py colgold` 产出，相对工作区根，如 `corpus/daizhige/colgold.jsonl`）。
    #: 空 = 关，关时产物逐字节不变。开了以后：某列 DP 切出的字数与表里双源一致的字数不同，
    #: 就按差值调格数**重切一次**；重切后字数恰好对上才采用，否则留原结果、记 `colgold_conflict` 旗。
    #: 人裁 `column-slots` 优先（有人裁的列不碰）；夹注列本期不碰。只对殿本这类有双源金标的书有意义。
    colgold_prior: str = ""
    colgold_fingerprint: str = ""        # 表内容 sha，开关开着时自动填（表一改 → Step3 判过期）
    #: **原生 YOLO 并格闸**（doc/design/19 块 D，2026-10-19）：缺省关，关时不读模型、产物逐字节不变。
    #: 开了以后整页跑一遍 yolo-tool 两段模型（`books/siku_zongmu/yolo_tool_infer`，onnxruntime），同列相邻两个
    #: 字格的墨迹框都有 ≥`yolo_cover` 落进同一个**正常高**（≤`yolo_max_h`×本页中位）的 YOLO 字框，
    #: 记一对「一字被切成两格」；有 k 对就把目标字数定为「现字数 − k」走 `apply_count_target` 重切，
    #: 字数恰好对上才采用。两个开关都开时先 D 后 C（D 改过的列 C 再按金标核一遍）。
    #: 输入是管线的 `ctx.raw_page`（灰度；`binarized_input` 的书是二值化后的图）转三通道，不是 yolo-tool 训练时的彩图。
    #: 门槛（0.6 / 1.3）只在殿本（灰度）和北行日錄上量过；二值化或预清理的书要开，先在该书上重量误并。
    yolo_merge: bool = False
    yolo_model_dir: str = ""             # yolo-tool 的 model/ 目录（内含 type/ slide/ 两个 best.onnx）；相对工作区根或绝对路径
    yolo_fingerprint: str = ""           # 两份 onnx 的 sha，开关开着时自动填（换模型 → Step3 判过期）
    yolo_conf: float = 0.25
    #: 0.5 → 0.6（10-19）：北行日錄 p18 列尾一格残墨 + 末字被同一个 YOLO 框各盖住 0.55/0.58，误并后整列切点挪位；
    #: 殿本测试 B 上 0.5 与 0.6 抓到的多切列一样（13/19，误报 0）。
    yolo_cover: float = 0.6
    yolo_max_h: float = 1.3

    @model_validator(mode="after")
    def _fill_yolo_fingerprint(self):
        if self.yolo_merge and not self.yolo_fingerprint:
            d = _colgold_path(self.yolo_model_dir)
            onnx = (d / "type" / "best.onnx", d / "slide" / "best.onnx")
            if not all(q.exists() for q in onnx):
                raise ValueError(f"yolo_merge 开着但 yolo_model_dir 下没有 type/、slide/ 的 best.onnx：{d}")
            key = ("yolo",) + _sig(*onnx)       # 每页都要建一次参数，两份模型约 116 MB，按签名缓存
            if key not in _FP_CACHE:
                from ..books.siku_zongmu.yolo_tool_infer import model_fingerprint
                _FP_CACHE[key] = model_fingerprint(d)
            object.__setattr__(self, "yolo_fingerprint", _FP_CACHE[key])
        return self

    @model_validator(mode="after")
    def _fill_colgold_fingerprint(self):
        if self.colgold_prior and not self.colgold_fingerprint:
            p = _colgold_path(self.colgold_prior)
            if not p.exists():
                raise ValueError(f"colgold_prior 开着但表不存在：{p}（先跑 scripts/dzg_import.py colgold）")
            key = ("colgold",) + _sig(p)
            if key not in _FP_CACHE:
                import hashlib
                _FP_CACHE[key] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            object.__setattr__(self, "colgold_fingerprint", _FP_CACHE[key])
        return self

    #: **逐列格位先验**（2026-10-19，`doc/research/切分现状梳理与新方向-2026-10-19.md` §六）：逐列格位表的路径
    #: （`scripts/dzg_layout.py` 由 daizhige 逐列本生成；相对工作区根或绝对路径）。空 = 关，关时产物逐字节不变。
    #: 开了以后，表里有的列（带任何人裁的列不碰——人裁按格号记，抬头级数一改格号就错位）：①抬头级数按表定
    #: （覆盖闸的 hint）；②DP 逐格软罚分——表说有字的格切成空、表说空的格切出字都付代价（`row_boundaries.slot_mask`）；
    #: ③两半都有字的夹注格走 `forced_jiazhu`、正文格走 `forced_main`；这样的列不再跑 colgold_prior／yolo_merge。只有一半有字的
    #: 夹注格（段尾奇数字、行内空格）不强制，交给现有判据与段端收编。殿本十册离线：普通正文页逐格全对 95.76% → 98.51%，劈字 19 → 0，
    #: 改坏 4 列。只对有逐列本的书有意义。2026-10-22 起缺省开（Sheldon：开关默认开、不再每册设）：缺省路径
    #: `DEFAULT_LAYOUT` 在本工作区不存在（没有逐列本的书）就当关；书 yaml 写了别的路径而表不存在照旧报错。
    #: 要关：书 yaml `params: {row_segment: {layout_prior: ""}}`。
    layout_prior: str = DEFAULT_LAYOUT
    layout_fingerprint: str = ""         # 表内容 sha，开关开着时自动填（表一改 → Step3 判过期）
    #: **自动配页**（2026-10-25，`steps/row_segment_pagemap.py`）：不读离线表，Step3 开跑前按全册列窗口与原图
    #: 和 daizhige 逐列本对齐、边跑边生成本册格位表（存 Step3 产物目录复用）。书级设置，三档：
    #: `off`（缺省，用上面 `layout_prior` 的离线表）／`loose`（配不准的页不带先验照切）／
    #: `strict`（整册配不上就报错拦下；有一份准确率很高的逐列本的书用，殿本 vol51 起）。开着时 `layout_prior` 不用。
    #: 第四档 `pins`（2026-10-31）：书有逐页钉位表（`page_map_pins`，corpus 下相对路径），按钉位直接出本册
    #: 格位表、不做墨量配页（史記文淵閣本；见 row_segment_pagemap 模块头）。
    page_map: Literal["off", "loose", "strict", "pins"] = "off"
    page_map_pins: str = ""
    page_map_fingerprint: str = ""       # daizhige＋本册钉页、改格＋算法版本，`RowSegmentStep.book_params` 填

    @model_validator(mode="after")
    def _fill_layout_fingerprint(self):
        if self.page_map == "pins" and not self.page_map_pins:
            raise ValueError("page_map: pins 要配 page_map_pins（corpus 下的逐页钉位表）")
        if self.page_map != "off":
            object.__setattr__(self, "layout_prior", "")
            return self
        if self.layout_prior and not self.layout_fingerprint:
            p = _layout_path(self.layout_prior)
            if not p.exists() and self.layout_prior == DEFAULT_LAYOUT:
                object.__setattr__(self, "layout_prior", "")
                return self
            if not p.exists():
                raise ValueError(f"layout_prior 开着但表不存在：{p}（先跑 scripts/dzg_layout.py）")
            key = ("layout",) + _sig(p)
            if key not in _FP_CACHE:
                import hashlib
                _FP_CACHE[key] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            object.__setattr__(self, "layout_fingerprint", _FP_CACHE[key])
        return self

    @model_validator(mode="after")
    def _fill_roster_ref_fingerprint(self):
        if self.roster_ref_corpus and self.roster_ref_pins and not self.roster_ref_fingerprint:
            from ..core.workspace import corpus_path
            from .context_decide import corpus_fingerprint
            dz = corpus_path(self.roster_ref_corpus)
            files = sorted(dz.glob("[0-9][0-9][0-9][0-9].jsonl")) if dz.is_dir() else [dz]
            object.__setattr__(self, "roster_ref_fingerprint", corpus_fingerprint(
                [*map(str, files), str(corpus_path(self.roster_ref_pins))]))
        return self

    @model_serializer(mode="wrap")
    def _drop_off_switches(self, handler):
        """缺省关的开关不进 dump（同 `border_detect`）：没开的书 `params_hash` 与加这些字段之前（v0.4.5）逐位相同，
        冻结册升 cv 版本不会被判成「参数变了」报警（D 10-19）。开着时照常进指纹。"""
        d = handler(self)
        if isinstance(d, dict):
            if not self.colgold_prior:
                d.pop("colgold_prior", None)
                d.pop("colgold_fingerprint", None)
            if not self.yolo_merge:
                for k in ("yolo_merge", "yolo_model_dir", "yolo_fingerprint", "yolo_conf", "yolo_cover", "yolo_max_h"):
                    d.pop(k, None)
            if not (self.roster_ref_corpus and self.roster_ref_pins):
                for k in ("roster_ref_corpus", "roster_ref_pins", "roster_ref_fingerprint"):
                    d.pop(k, None)
            if not self.layout_prior:
                d.pop("layout_prior", None)
                d.pop("layout_fingerprint", None)
            if self.page_map == "off":
                d.pop("page_map", None)
                d.pop("page_map_fingerprint", None)
            if self.page_map != "pins":
                d.pop("page_map_pins", None)
        return d

    @model_validator(mode="after")
    def _fill_judge_fingerprint(self):
        # 与 glyph_match.GlyphMatchParams.db_fingerprint 同一套路：模型是外部可变状态，
        # 不进指纹的话换了权重产物还显示 fresh。权重缺失时为空串 → 与裁判可用时指纹不同。
        if self.cut_judge == "unet" and not self.judge_fingerprint:
            object.__setattr__(self, "judge_fingerprint", ckpt_fingerprint())
        # 字形库精修：只在开关开着时解析库路径、填指纹——关着时参数逐字段不变（同 seed_admit.human_fingerprint）
        if self.roster_glyph_refine:
            if not self.roster_glyph_db:
                from ..core.workspace import glyph_db_path
                object.__setattr__(self, "roster_glyph_db", str(glyph_db_path()))
            if not self.roster_glyph_fingerprint:
                from .glyph_match import db_fingerprint
                object.__setattr__(self, "roster_glyph_fingerprint", db_fingerprint(self.roster_glyph_db))
        return self


@register_step
class RowSegmentStep(Step):
    spec = StepSpec(
        id="row_segment", title="Step3 单列文字切分", version="1.42", unit="column",   # 1.42：职名页分支认写本（史記文淵閣本）——斜贴邻字的偏右小「臣」按全页臣行拆出、列端扁框线残段不当字、落在印里的字丢掉（读 seals）；1.41：大印下的列等距格网在印外比按打分的格网多劈 ≥2 个字时按打分挑（挤格列，vol48 p34、vol46 p106）；1.40：layout_prior 候选格网加「表整列挪一格」（格号 ±1，违表严格更少才选；大印下只在等距格网间比违表），整理本起格差一格的列（vol68 p31 c7–c9）不再丢首字、列末多空字格；1.39：自动配页 page_map（off/loose/strict，书级；开着时 Step3 开跑前按全册列窗口与 daizhige 对齐、边跑边生成本册格位表，见 row_segment_pagemap.py），缺省 off 逐字节不变；1.38：候选格网打分加格高不匀（_uneven，排在劈字后、穿字前）；选中的格网有一格挤两字时在字缝补一条格线、按打分去掉一条（_merged_cuts，殿本个别列字排得比整页格网密）；1.37：layout_prior 开着而表里没有本册就报错（不再悄悄当关）；1.36：干净格线两侧格高偏 >15% 也过 U-Net 探针；扩池候选与 U-Net 几乎一致、穿墨少就自动改选（字内空隙里的格线把字头/点切给上一格）；1.35：layout_prior 缺省开（缺省表不在当关）；1.34：大印压着列首的列（_under_stain）直接取表的等距格网，不再按坏格挑（印泥斑点让闸抬头、DP 挤格，字整列错一格而格号集合不变）；1.33：列端表空格的印改读印章定位 `seals` 产物——大印按框、小印按笔画覆盖区量（_in_seal），去掉模板窗口找印与表空段墨团（_empty_zone_seal），并纠正印框与格坐标空间不一致（印框原是左上原点）；1.32：模板没认出的印（空心印）和模板框没盖住的印边：相邻列的表空段同高都有像字的墨，就当印框（_empty_zone_seal）；1.31：列端表空格里被切成雙行小注半格的印章墨也记空；1.30：表说半格、判据认成單行小注的格按半格发（jiazhu_a/b）；1.29：列端表空格里墨只是一两道竖线的格记空（印框边、界行残段）；1.28：印框记空挪进候选格网打分之前（同框线碎墨，先记空再打分），單行小注格也记；1.27：印框记空门槛 0.35 → 0.30；1.26：印框里的列端表空格记空（印章模板命中，同 seed_admit 盖章判空）；layout_prior 表说只有一半有字的夹注格（half），列里有雙行段就按段缝拆、只发墨多的一半；1.25：列端表空格的墨大多连不成笔画（印章斑点）也记空；1.24：layout_prior 候选格网加等距格网（books/siku_zongmu/row_grid，格线就近落缝），各候选先把列端表空格里不像字的墨记空再打分，不像字加「越过界行」（印章、墨污），卷末整列空的列按表空列处理；1.23：layout_prior 候选格网（表／闸抬头／无先验）按（劈字、违表、穿字）挑，列端表空格段的框线碎墨记空，表认下的字格标 layout_char 给 Step4；1.22：发 v0.4.8 时并入 main 的人工指定整列格 manual_cells（main 上记作 1.20：lookup.resolved_manual_cells，职名页／卷题切不对的列由人框定，没有指定的列逐字节不变），与本线 1.20／1.21 合一；1.21：layout_prior 列端框线残渣记空（表说该空的物理首／末格只有框线）；1.20：layout_prior 抬头级数与闸不一致时两种格网都切、取穿字少的（殿本 vol04 产物包 p84/p65/p127）；1.19：逐列格位先验 layout_prior（daizhige 逐列本，默认关；命中的列不跑 colgold_prior／yolo_merge）；1.18：逐列字数先验 colgold_prior、原生 YOLO 并格闸 yolo_merge（doc/design/19，都默认关）；1.17：职名页密排段按字形库重切 roster_glyph_refine（overview#450，默认关）；1.16：列端虚线残段记空白 dash_blank（overview#376，默认关）；1.15：职名页分支 roster_pages（overview#450，默认关）；1.14：人裁「正文当小注」的格从夹注段里摘掉、按整格出（forced_main，overview#415/#436）；1.13：人裁「小注当正文」的格强制按雙行小注从中间拆（forced_jiazhu，2026-09-30）；1.12：列里残留的下版框线当下界（overview#266）；1.11：單行小注自成 kind=jiazhu_solo（此前借 jiazhu_a 的壳）
        consumes=("gate_manifest", "column_windows", "column_image"), optional_consumes=("seals",), produces=("cells",),
        params=RowSegmentParams,
        code_deps=("open_guji_cv.books.siku_zongmu.row_boundaries", "open_guji_cv.books.siku_zongmu.row_grid", "open_guji_cv.books.siku_zongmu.jiazhu_split",
                   "open_guji_cv.seg.warp", "open_guji_cv.seg.profile", "open_guji_cv.books.siku_zongmu.column", "open_guji_cv.seg.seam",
                   "open_guji_cv.seg.cut_select", "open_guji_cv.books.siku_zongmu.roster_segment",
                   "open_guji_cv.books.siku_zongmu.roster_glyph", "open_guji_cv.books.siku_zongmu.yolo_tool_infer", "open_guji_cv.steps.occlusion",
                   "open_guji_cv.steps.seal_detect", "open_guji_cv.steps.row_segment_pagemap",
                   "open_guji_cv.utils.page_align", "open_guji_cv.utils.daizhige"),
        soft_params=("roster_glyph_fingerprint",),
        path_params=("roster_glyph_db", "colgold_prior", "yolo_model_dir", "layout_prior", "roster_ref_corpus", "roster_ref_pins", "page_map_pins"),
    )

    def book_params(self, p: "RowSegmentParams", ctx: RunContext) -> "RowSegmentParams":
        """自动配页开着时，格位表那一项指纹按本册算（`row_segment_pagemap.fingerprint`）。"""
        if p.page_map == "off" or p.page_map_fingerprint:
            return p
        from .row_segment_pagemap import fingerprint
        fp = fingerprint(ctx.book.id, p.page_map_pins if p.page_map == "pins" else "")
        return type(p)(**{**p.model_dump(), "page_map_fingerprint": fp})

    def prepare(self, ctx: RunContext, pages: list[int]) -> None:
        """整步开跑前：自动配页开着就先把本册配页算好（或确认缓存还新），strict 配不上在这里拦下。"""
        p: RowSegmentParams = ctx.params_for(self)  # type: ignore[assignment]
        if p.page_map != "off":
            from .row_segment_pagemap import ensure
            ensure(ctx, p.page_map, p.page_map_pins)

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentParams = ctx.params_for(self)  # type: ignore[assignment]
        n_body = p.n_body_slots or ctx.book.chars_per_line
        gate: GateManifest = ctx.product("gate_manifest", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        from ..feedback.lookup import resolved_manual_cells as _resolved_manual
        manual = {k[1]: v for k, v in _resolved_manual(ctx.book.id).items() if k[0] == page}
        if p.roster_pages and page in set(_expand_pages(p.roster_pages)):
            pc = self._run_roster(ctx, p, page, gate, wins)
            return {"cells": _apply_manual_cells(pc, manual, gate, wins)}
        # 人裁回流：workspace 裁决表里这本书已裁决的切点（feedback/lookup.py，
        # **不读 open-guji-dataset**），按 (页,列) 筛出 slot_above → kind 传给
        # segment_column 收敛候选。裁决不进指纹，该页下次重跑才生效（见 lookup 注）。
        from ..feedback.lookup import resolved_cuts as _resolved_cuts
        from ..feedback.lookup import resolved_slots as _resolved_slots
        book_resolved = _resolved_cuts(ctx.book.id)
        # 同一条回流路径的兄弟：逐列字数覆盖（`review/slot_count_cards.py`）。
        # `chars_per_line` 是页级版式常量，DP 硬切；少数列真的比常量多/少刻了
        # 一个字时（bxgb p33c19 实测 22 字 vs 常量 21），没有可靠的几何信号能
        # 自动探测（格高/period 比值测过，两个方向都不可靠，见
        # feedback_cell_height_not_merge_signal），只能人核对后写回。
        #
        # 同一条裁决还带 `uniform`（2026-09-20）：字数对了不等于**字距**均匀。
        # p33c19 就是字数 22 给对了、DP 仍把首字「尉」劈成两格——等距先验比
        # 墨量判据贵五倍（账见 row_boundaries.NONUNIFORM_LAM）。标了非均匀的列
        # 把 lam 降下来，其余列一字不动。
        book_slots = _resolved_slots(ctx.book.id)
        # 第三个兄弟：人指认的單行小注格（判据落空的那一型，见 lookup.resolved_solo_notes）
        from ..feedback.lookup import resolved_solo_notes as _resolved_solo
        book_solo = _resolved_solo(ctx.book.id)
        # 第四个兄弟（2026-09-30）：人指认的雙行小注格（判据没认出的短版本小注），不看判据从中间拆
        from ..feedback.lookup import resolved_forced_jiazhu as _resolved_forced_jz
        book_forced_jz = _resolved_forced_jz(ctx.book.id)
        # 第五个兄弟（2026-10-06，overview#415/#436）：反向——人指认的整宽正文格，Step3 别把它劈成 a/b
        from ..feedback.lookup import resolved_forced_main as _resolved_forced_main
        book_forced_main = _resolved_forced_main(ctx.book.id)
        # 第六个兄弟（2026-10-27）：人裁逐列抬头级数。Step1 按同一张表补了抬头框、列窗已往上开；这里级数听裁决，
        # 表和闸都不再改（不出「抬头按闸」候选）。表的级数与裁决不同时，表的字按先后挪到裁决的格号上（_reraise）
        from ..feedback.lookup import resolved_head_raise as _resolved_head_raise
        book_head_raise = _resolved_head_raise(ctx.book.id)
        # 候选池裁判（U-Net，进程内单例）；权重/torch 不可用时为 None → segment_column 按旧规则走
        judge = get_judge() if p.cut_judge == "unet" else None
        # 人拖过的切线钉住（lookup.resolved_pins，只收带页面坐标的裁决；生效时机同 resolved_cuts）
        from ..feedback.lookup import resolved_pins as _resolved_pins
        book_pins = _resolved_pins(ctx.book.id, ctx.store)
        colgold = load_colgold(p.colgold_prior, ctx.book.id) if p.colgold_prior else {}
        yolo_boxes: list = []
        if p.yolo_merge:
            import cv2
            raw = ctx.raw_page(page)
            bgr = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR) if raw.ndim == 2 else raw
            _, ych = _yolo(p.yolo_model_dir).infer(bgr, slide_conf=p.yolo_conf)
            yolo_boxes = [(b.x0, b.y0, b.x1, b.y1) for b in ych if b.conf >= p.yolo_conf]
        if p.page_map != "off":
            from .row_segment_pagemap import layout_for
            layout = layout_for(ctx, p.page_map, p.page_map_pins)
        else:
            layout = load_layout(p.layout_prior, ctx.book.id) if p.layout_prior else {}
        if p.layout_prior and not layout:
            # 表在、开关开着，表里却一行本册都没有：多半是新册没生成表（殿本 vol11–20 首跑就这样悄悄当关，
            # 逐格全对 94.7% vs 带表 100%）。宁可拦下，不悄悄退回无先验。
            raise ValueError(f"layout_prior 表 {_layout_path(p.layout_prior)} 里没有 {ctx.book.id}："
                             "先跑 scripts/dzg_import.py map 与 scripts/dzg_layout.py 补这一册；"
                             "确实不要先验的书在书 yaml 写 params.row_segment.layout_prior: \"\"")
        # 等距格网（books/siku_zongmu/row_grid）：只给逐列格位先验命中的页算，是那里的候选格网之一
        grids = {}
        # 印框（列端表空格记空的判据之一）：同样只给格位先验命中的页用
        seals = _page_seals(ctx, page) if any(pg_ == page for (pg_, _c) in layout) else []
        if gate.period is not None and any(pg_ == page for (pg_, _c) in layout):
            grid_cols = []
            for gc in gate.columns:
                if p.only_admitted and not gc.admitted:
                    continue
                gimg = ctx.image("column_image", column_key(page, gc.col))
                grid_cols.append(dict(col=gc.col, img=gimg, content_x=gc.content_x or (0, gimg.shape[1]),
                                      border_top=gc.border_top, border_bottom=gc.border_bottom,
                                      n_raised=max(p.n_raised, getattr(gc, "n_raised_hint", 0) or 0)))
            grids = fit_page_grids(grid_cols, gate.period, p.ink_threshold)
        out: list[ColumnCells] = []
        for gc in gate.columns:
            # 逐列格数：页级参数与闸给的 hint 取大者。hint 是「这一列墨跨度
            # 装得下几个字」（见 GateColumn.n_raised_hint）——同一页上有的抬头列
            # 多一格、有的不多，页级参数给不出这个差别，DP 只能丢掉首字。
            n_raised_col = max(p.n_raised, getattr(gc, "n_raised_hint", 0) or 0)
            hr_verdict = book_head_raise.get((page, gc.col))
            if hr_verdict is not None:
                n_raised_col = hr_verdict
            # 版框装不下 n_body 格的页（vol01/5 只有 20 行）按实际行数切，见
            # row_boundaries.effective_body_slots
            n_body_col = effective_body_slots(n_body, gc.border_top, gc.border_bottom, gate.period)
            # 人裁逐列字数覆盖优先于上面两条自动判据——人是终审，跟
            # `_apply_resolved_cut` 里"人裁收敛成功就不再是升级"同一条纪律。
            slot_override = book_slots.get((page, gc.col))
            if slot_override is not None:
                n_body_col = slot_override.n_slots
            col_resolved = {slot: kind for (pg, col, slot), kind in book_resolved.items()
                            if pg == page and col == gc.col}
            # 带任何人裁（逐列字数、切点、钉线、强制正文/小注）的列：人裁都按格号记，下面三个结构先验
            # 一改格数或抬头级数，格号就对不上，所以一律不动（人裁为终裁）
            human_col = (slot_override is not None or bool(col_resolved)
                         or any(pg_ == page and c_ == gc.col for (pg_, c_, _s) in book_pins)
                         or (page, gc.col) in book_solo or (page, gc.col) in book_forced_jz
                         or (page, gc.col) in book_forced_main)
            # 逐列格位先验（layout_prior）：抬头级数按表定（不只往上补——闸给书名列多加的那格
            # 抬头余量会让书名首字编成 -1、整列格号差一格），DP 加逐格掩码，夹注 / 正文格强制
            lay = _layout_row(layout, page, gc.col) if not human_col else None
            in_table = lay is not None
            top_slack = gc.top_slack
            lay_kw: dict = {}
            forced_jz = book_forced_jz.get((page, gc.col))
            forced_main = book_forced_main.get((page, gc.col))
            lay_alt = None     # 闸版格网（抬头级数听闸、表只管格的有无），见下
            gate_raised = n_raised_col
            if lay is not None:
                if hr_verdict is not None:
                    lay = _reraise(lay, hr_verdict)
                occ = set(lay["slots"])
                want = int(lay.get("raised", 0))
                if want != n_raised_col:
                    lay_alt = (n_raised_col, gc.top_slack, {s for s in occ if s > 0 or s >= -n_raised_col})
                n_raised_col = want
                top_slack = gc.border_top if want else gc.top_slack
                lay_kw, forced_jz, forced_main = _layout_kw(lay, occ, n_body_col, n_raised_col)
            base = dict(col=gc.col, n_body_slots=n_body_col, n_raised=n_raised_col,
                        period=gate.period, ref_w=gate.ref_w, content_x=gc.content_x,
                        border_top=gc.border_top, border_bottom=gc.border_bottom,
                        top_slack=top_slack)
            if p.only_admitted and not gc.admitted:
                out.append(ColumnCells(ok=False, error="未过交接闸: " + "; ".join(gc.reject), **base))
                continue
            if gate.period is None:
                out.append(ColumnCells(ok=False, error="页级 period 缺失", **base))
                continue
            img = ctx.image("column_image", column_key(page, gc.col))
            def _seg(n_body: int, alt: tuple | None = None, grid: bool = False, bounds: list[float] | None = None):
                n_r, t_s, l_kw, f_jz, f_main = (alt if alt is not None else
                                                (n_raised_col, top_slack, lay_kw, forced_jz, forced_main))
                return segment_column(
                    img, period=gate.period, n_body_slots=n_body, n_raised=n_r,
                    border_top=gc.border_top, border_bottom=gc.border_bottom, ref_w=gate.ref_w,
                    top_slack=t_s, content_x=gc.content_x,
                    ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio,
                    raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu, seam_band=p.seam_band,
                    resolved_cuts=col_resolved or None, cut_judge=judge,
                    pinned_cuts={s_: y_ for (pg_, c_, s_), y_ in book_pins.items()
                                 if pg_ == page and c_ == gc.col} or None,
                    forced_solo=book_solo.get((page, gc.col)),
                    forced_jiazhu=f_jz,
                    forced_main=f_main,
                    detect_bottom_bar=p.detect_bottom_bar,
                    grid_bounds=bounds if bounds is not None else grids[gc.col].bounds(n_body, n_r) if grid else None, **l_kw,
                    **({"dash_blank": (p.dash_h_frac, p.dash_w_frac)} if p.dash_blank else {}),
                    **({} if slot_override is None or slot_override.uniform
                       else {"lam": NONUNIFORM_LAM}))
            r = _seg(n_body_col)
            prior_flags: list[str] = []
            # 逐列格位先验命中的列，候选格网按图挑：
            #   表格网（抬头级数、格的有无都按表）；
            #   闸抬头格网（表与闸的抬头级数不一致时：抬头听闸，表只管格的有无）；
            #   上面每一种抬头级数各再出一张等距格网（books/siku_zongmu/row_grid：格号按整列等距排，格线就近落缝，不跑 DP）；
            #   无先验格网（以上都劈了字、且不看表切出的字比表少时才用：表的字图上装不下，比如整理本分行和刻本不同）；
            #   挤格补线格网（选中的格网有一格挤着两个字时：在字缝补一条格线、按打分去掉一条，见 _merged_cuts）。
            # 每张格网先把列端表空格里不像字的墨记空（_blank_frame_junk），再打分：坏格数 = 劈开的字 + 违表的格，取最少；
            # 一样多时宁可违表也不劈字，再比格高不匀（_uneven：殿本格高均匀，缩框前「一」「二」也占满一格），再比穿字格线，
            # 再打平按上面的顺序（DP 格网在等距格网前）。
            # - 闸抬头：表管「有没有抬头字」，图上有几个物理格位要看列图。殿本 vol04 产物包：①表说抬头、列图却从
            #   版框顶起截（p84 c5、p65 c8「御」「欽」没截到）；②表说不抬头、闸给了余量的低起列（p127 c1–2）。
            #   但闸多给的那格在书名列上会把首字吸进 -1，一律听闸也不行（vol04 新坏 10 列），所以按图二选一。
            # - 违表格数算进坏格数、排在穿字格线前：掩码是软约束，「二」这类上下两横中间有空的字，格线落在两横之间不穿墨，
            #   只比穿字会选中违表劈「二」的那种（vol06 p94 c6，「二」上横被单切一格后丢掉）。
            # - 等距格网（1.24，用户 2026-10-21：殿本正文每列严格 21 格、格高相近，空白也占格）：DP 在列端印章、墨损、
            #   版框残墨处会把格挤歪，首字前多出一格、整列格号错位（vol04 p6 c2、p8 c2/c4/c8，vol06 p33 c4）。
            #   等距格网不看这些墨排格号，只在它坏格更少时才选上；格线落缝后穿字格线反比 DP 少。
            # - 先记空再打分：印章、墨污占着表空格时，DP 格网和等距格网都「违表」，比不出谁对；记空之后只剩真差别。
            # - 无先验：表说 6 字、图上只有 5 字的短列（vol07 p44 c8「臨御六十一年」，「臨」不在这一列），
            #   硬按表切只能劈字（坏格 1／1），无先验少一字（坏格 1／0）→ 取无先验。这时这一列当作没有表（不记空框线、
            #   不标 layout_char）。不看表切出的字不比表少时不换：那是图上多了东西（版框线、斑驳底纸），不是表多了字
            #   （vol04 p6 c9 版框线进了列图、vol09 p164 c1 卷端页，换了反而整列格号错位或多切碎格）。
            # - 大印下的列（1.34，印章系统化第 3 期）：卷首叶、卷端页的大印压着的列（列首格一半以上在 `seals` 的大印框里，
            #   `_under_stain`），印泥斑点连着字，劈字、穿字都量不准——闸会把列首斑点当抬头字（vol04 p3 c2/c3、vol05 p3 c3、
            #   vol10 p88 c1，表 0 格、闸 1 格），DP 会为躲斑点把格挤歪（vol07 p2 c1「定四」并一格、vol09 p70 c1）。格号集合照样
            #   对得上，只有 structcmp 的对位口径看得见。殿本格网严格，这些列直接取表的等距格网（抬头听表，格线就近落缝），不打分。
            # 列端记空（_blank_frame_junk）：表说该空、在表的首字之前或末字之后（整列空的列就是整列）的字格，墨不像字就
            # 记空：只有框线那种满宽横墨或碎点，或者墨越过界行（印章、墨污）。掩码故意不罚满宽密行（不然 DP 为躲框线
            # 去并上面的字，见 row_boundaries.SLOT_MASK_ROWS），所以版框横线落进列端那一格时会被切成「字」（殿本 vol04
            # p6 c2、p8 c2，vol05 p147 c1）。列中段的碎墨（卷端页、整页破损页上印断的字，vol09 p164「經部十七」）不碰——
            # 人审率分析的教训：破损页的空位不能批量判非字。1.21 实测改空 647 格（逐格看图都是框线、竖线、碎点）；
            # 1.23 从物理首／末格放宽到表空格这一段；1.24 加越界墨（列首大印 vol09 p68/p70/p164、vol10 p175，
            # 卷末印章 vol09 p162）与整列空的列。
            if lay is not None and r is not None:
                cands = [(r, n_raised_col, top_slack, occ, "")]
                if lay_alt is not None:
                    n_r2, t_s2, occ2 = lay_alt
                    r2 = _seg(n_body_col, (n_r2, t_s2) + _layout_kw(lay, occ2, n_body_col, n_r2))
                    if r2 is not None:
                        cands.append((r2, n_r2, t_s2, occ2, f"layout_raise_gate：抬头按闸 {n_r2} 格（表 {int(lay.get('raised', 0))} 格）"))
                # 表整列挪一格（表的字按先后不动、格号整体 ±1）：整理本的起格偶有差一格的（vol68 p31 c7–c9「右釋家類」
                # 首字在 2 号格、表记 3 号起；vol45 p17 c2、p24 c4 列末多一个空字格），格线不变、只是列端一头多一字一头少一字。照样打分，
                # 违表格数严格更少才选上（同分按原表）。
                for c_ in list(cands):
                    for d_ in (-1, 1):
                        occ_s = _shift_occ(c_[3], d_, n_body_col)
                        if occ_s is None:
                            continue
                        lay_s = _shift_lay(lay, d_)
                        rs_ = _seg(n_body_col, (c_[1], c_[2]) + _layout_kw(lay_s, occ_s, n_body_col, c_[1]))
                        if rs_ is not None:
                            cands.append((rs_, c_[1], c_[2], occ_s, f"layout_shift{d_:+d}" + (f"（{c_[4]}）" if c_[4] else "")))
                if gc.col in grids:
                    for c_ in list(cands):
                        rg = _seg(n_body_col, (c_[1], c_[2]) + _layout_kw(lay, c_[3], n_body_col, c_[1]), grid=True)
                        if rg is not None:
                            cands.append((rg, c_[1], c_[2], c_[3], "uniform_grid" + (f"（{c_[4]}）" if c_[4] else "")))

                def _score(c):
                    k_split = _split_chars(img, c[0].cells, gate.period, p.ink_threshold)
                    k_miss = _mask_misses(c[0].cells, c[3])
                    return (k_split + k_miss, k_split, _uneven(c[0].cells, gate.period),
                            _cut_rows(img, c[0].cells, p.ink_threshold))
                wrec = wins.column(gc.col)
                mapper = None if wrec is None else ColumnMapper(
                    page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(), wrec.top_y, wrec.bottom_y)
                in_seal = _in_seal(seals, mapper, img, p.ink_threshold)
                junk = [_blank_frame_junk(img, c[0].cells, c[3], gc.content_x, p.ink_threshold, gate.period, in_seal)
                        for c in cands]
                scores = [_score(c) for c in cands]
                # 大印压着列首：格网直接取表的等距格网，不比坏格（见上「大印下的列」）
                stained = in_seal is not None and _under_stain(
                    seals, mapper, gc.content_x or (0, img.shape[1]), gc.border_top, gate.period)
                best = next((i for i, c in enumerate(cands) if c[4] == "uniform_grid"), None) if stained else None
                if best is not None:
                    # 大印下也认表挪一格的等距格网，但只比违表格数（劈字、穿字在印泥里量不准），严格更少才换
                    sh = [i for i, c in enumerate(cands) if c[4].startswith("uniform_grid（layout_shift")]
                    best = min([best] + sh, key=lambda i: (scores[i][0] - scores[i][1], i))
                    # 挤格列（字比 21 格多、字距不匀）在大印下也有：等距格网在印外劈了一串字时，不再硬取等距格网（vol48 p34 c2、
                    # vol46 p106 c9）。印泥只让印框里的格量不准，所以只数印外的劈字：比按打分挑出的格网多 STAIN_GRID_MARGIN 条
                    # 以上就按打分挑。卷首叶题列字都在印里，印外没字可劈，照旧取等距格网（vol28 p1 c1）。
                    def _split_out(i):
                        return _split_chars(img, [c for c in cands[i][0].cells if not in_seal(c)], gate.period, p.ink_threshold)
                    plain_ = min((i for i, c in enumerate(cands) if "layout_shift" not in c[4]), key=lambda i: (scores[i], i))
                    if _split_out(best) - _split_out(plain_) >= STAIN_GRID_MARGIN:
                        best, stained = None, False
                if best is None:
                    if min(s_[1] for s_ in scores) > 0:
                        r3 = _seg(n_body_col, (gate_raised, gc.top_slack, {}, None, None))
                        if r3 is not None and _n_chars(r3.cells) < len(occ):
                            cands.append((r3, gate_raised, gc.top_slack, occ, "layout_off"))
                            junk.append(0)
                            scores.append(_score(cands[-1]))
                    # 表挪一格的候选只在坏格数严格更少时才选（格高不匀、穿字打平不算数：格线一样，只是列端的字／空换了位）
                    key_ = lambda i: (scores[i], i)
                    plain = [i for i, c in enumerate(cands) if "layout_shift" not in c[4]]
                    shifted = [i for i, c in enumerate(cands) if "layout_shift" in c[4]]
                    best = min(plain, key=key_)
                    if shifted and scores[min(shifted, key=key_)][0] < scores[best][0]:
                        best = min(shifted, key=key_)
                    # 挤格：选中的格网里有一格挤着两个字（殿本个别列字排得比整页格网密，如挖改处多刻一字）→ 在两字的缝里
                    # 补一条格线、再去掉一条，格数不变；去哪条按 _score 挑，坏格、劈字不多才换
                    for _ in range(MERGE_MAX_FIX):
                        cuts = _merged_cuts(img, cands[best][0].cells, gate.period, p.ink_threshold)
                        if not cuts or cands[best][4] == "layout_off":
                            break
                        rb, n_rb, t_sb, occ_b, why_b = cands[best]
                        lines = sorted(rb.boundaries + cuts[:1])
                        alt = (n_rb, t_sb) + _layout_kw(lay, occ_b, n_body_col, n_rb)
                        trial = []
                        for i in range(len(lines)):            # 去掉第 i 条；去端线 = 丢掉列端那一格
                            ri = _seg(n_body_col, alt, bounds=lines[:i] + lines[i + 1:])
                            if ri is None:
                                continue
                            ji = _blank_frame_junk(img, ri.cells, occ_b, gc.content_x, p.ink_threshold, gate.period, in_seal)
                            if len(_merged_cuts(img, ri.cells, gate.period, p.ink_threshold)) < len(cuts):
                                ci = (ri, n_rb, t_sb, occ_b, "layout_unmerge" + (f"（{why_b}）" if why_b else ""))
                                trial.append((_score(ci), i, ci, ji))
                        if not trial or min(trial)[0][:2] > scores[best][:2]:
                            break
                        s_, _i, ci, ji = min(trial)
                        cands.append(ci)
                        junk.append(ji)
                        scores.append(s_)
                        best = len(cands) - 1
                if best:
                    r, n_raised_col, top_slack, occ, why = cands[best]
                    base = dict(base, n_raised=n_raised_col, top_slack=top_slack)
                    prior_flags.append(f"{why}{'（大印下）' if stained else ''}：坏格／劈字／格高不匀／穿字 "
                                       + "→".join("/".join(map(str, scores[i])) for i in (0, best)))
                    if why == "layout_off":
                        lay = None
                if junk[best]:
                    prior_flags.append(f"layout_frame_junk：列端 {junk[best]} 格的墨不像字（框线／碎墨／越界墨／印框），记空")
            # C、D 会改格数重切：人裁列不动（见上）；逐列格位先验命中的列已按格位切，也不再叠
            # 逐列字数先验与 YOLO 并格（同列互斥，两套先验叠在一列上会打架）
            skip_cd = human_col or in_table
            g = colgold.get((page, gc.col))
            k_pairs = 0
            if r is not None and yolo_boxes and not skip_cd and not _has_jiazhu(r.cells):
                k_pairs = self._yolo_pairs(r, img, wins, gc.col, page_w, yolo_boxes, p)
            # 先 D 后 C：两者修好的列几乎不重叠（测试 B：C 修 10、D 修 11、并集 13），
            # 「有金标时只让 D 提议、金标定采不采」那版实测漏掉 D 独有的两列（设计变更记录）。
            if r is not None and k_pairs and not skip_cd:
                r, n_new, fl = apply_count_target(r, _seg, n_body_col, _n_chars(r.cells) - k_pairs, "yolo")
                prior_flags += fl
                if n_new != n_body_col:
                    n_body_col = n_new
                    base = dict(base, n_body_slots=n_body_col)
            if r is not None and g is not None and not skip_cd:
                r, n_new, fl = apply_count_target(r, _seg, n_body_col, int(g["dzg"]["n"]), "colgold",
                                                  count=colgold_count(g["dzg"], img, p.ink_threshold))
                prior_flags += fl
                if n_new != n_body_col:
                    n_body_col = n_new
                    base = dict(base, n_body_slots=n_body_col)
            if r is None:
                out.append(ColumnCells(ok=False, error="弹性 DP 无解", **base))
                continue
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            n_total = n_body_col + n_raised_col
            cells = []
            for c in r.cells:
                pos = _slot_to_pos(c.slot, n_raised_col)
                if not 1 <= pos <= n_total:
                    raise ValueError(f"slot {c.slot} 换算出的物理位置 {pos} 越界（总格数 {n_total}）")
                cells.append(CellRec(
                    slot=c.slot, pos=pos, y0=float(c.y0), y1=float(c.y1),
                    x0=float(c.x0), x1=float(c.x1), kind=c.kind, sub=c.sub, order=int(c.order),
                    gap_center=None if c.gap_center is None else float(c.gap_center),
                    ink_ratio=float(c.ink_ratio), raised=bool(c.raised),
                    suspect_jiazhu_body=bool(getattr(c, "suspect_jiazhu_body", False)),
                    seam_top=c.seam_top, seam_bottom=c.seam_bottom,
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2)) for x, y in mapper.quad_tr(c.x0, c.y0, c.x1, c.y1)]),
                    # 表认下的字格：Step4 的列端渣格闸不再拿图像判据把它判空（「一」「二」在列端形同框线）
                    flags=["layout_char"] if lay is not None and c.kind != "blank" and c.slot in occ else [],
                ))
            flags: list[str] = list(prior_flags)
            if r.bottom_bar_y is not None:
                # 下界换成了列里认出的下版框线（2026-09-28，overview#266）。border_bottom
                # 一并改写：Step4 拿它当 frame_bottom 提示，把条带开到这里、在它附近找框——
                # 还给 Step2 的值，Step4 就在框下白纸上找框，找不到，框墨进图块。
                flags.append(f"bottom_bar：下版框线在列图 y={r.bottom_bar_y:.0f}，"
                             f"高出 border_bottom {base['border_bottom'] - r.bottom_bar_y:.0f} 行")
                base = dict(base, border_bottom=float(r.bottom_bar_y))
            out.append(ColumnCells(ok=True, boundaries=[float(b) for b in r.boundaries], flags=flags,
                                   cells=cells, cut_candidates=[
                                       CutPointCandidates(
                                           k=cp.k, y=cp.y, slot_above=cp.slot_above,
                                           slot_below=cp.slot_below, chosen=cp.chosen,
                                           chosen_by=cp.chosen_by,
                                           escalate=cp.escalate, escalate_reason=cp.escalate_reason,
                                           origin=cp.origin,
                                           candidates=[SeamCandidate(
                                               kind=c.kind, y=c.y, seam_ink=c.seam_ink,
                                               dev_max=c.dev_max, agree=c.agree, dis_unet=c.dis_unet)
                                               for c in cp.candidates],
                                       ) for cp in r.cut_candidates],
                                   **base))
        pc = PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)
        pc = self._header_columns(ctx, p, page, gate, wins, pc)
        return {"cells": _apply_manual_cells(pc, manual, gate, wins)}

    def _header_columns(self, ctx: RunContext, p: RowSegmentParams, page: int,
                        gate: GateManifest, wins: PageWindows, pc: PageCells) -> PageCells:
        """套书认得出的卷端标题列（卷题、撰者行、篇题；`header_cols`，只史記有）改走职名页分支按整理本字数切。
        写本这些行字距不跟格网（小数字「第二十二」挤、撰者行疏），格网切会劈字、把字脚分给下一格。
        没开整理本重切（roster_ref_corpus）或套书没有 `header_cols` 时原样返回。"""
        if not (p.roster_ref_corpus and p.roster_ref_pins):
            return pc
        import importlib
        from ..core.seg_set import resolve
        mod = importlib.import_module(resolve(ctx.book, "open_guji_cv.books.siku_zongmu.roster_segment"))
        header_cols = getattr(mod, "header_cols", None)
        if header_cols is None:
            return pc
        from ..core.workspace import corpus_path
        refs = mod.page_ref_lines(corpus_path(p.roster_ref_corpus), corpus_path(p.roster_ref_pins), ctx.book.id, page)
        cols = header_cols(refs or {})
        # 大印压着的列不改：印泥斑点和印文笔画在几何切里成串成块，按字数重切会把印切成字（卷首页的大印）
        seals = _page_seals(ctx, page)
        for cc in pc.columns:
            qs = [xy for c in cc.cells if c.quad_page for xy in c.quad_page]
            if cc.col in cols and qs and any(
                    s[0] < max(x for x, _ in qs) and min(x for x, _ in qs) < s[2] for s in seals):
                cols.discard(cc.col)
        if not cols:
            return pc
        got = {cc.col: cc for cc in self._run_roster(ctx, p, page, gate, wins, only=cols).columns if cc.ok}
        out = []
        for cc in pc.columns:
            new = got.get(cc.col)
            if new is None:
                out.append(cc)
                continue
            # 格号沿用格网切出的起格（标题行在格网里的起始格，与格位表、整理本格位一致），
            # 职名分支自己从 1 数，下游按格号对整理本会错位
            first = [c.slot for c in cc.cells if c.kind != "blank" and c.slot >= 1]
            off = min(first) - 1 if cc.ok and first else 0
            if off:
                new = new.model_copy(update=dict(
                    n_body_slots=new.n_body_slots + off,
                    cells=[c.model_copy(update=dict(slot=c.slot + off, pos=c.pos + off)) for c in new.cells]))
            out.append(new)
        return PageCells(page=pc.page, period=pc.period, ref_w=pc.ref_w, columns=out)


    @staticmethod
    def _yolo_pairs(r, img, wins, col: int, page_w: int, yolo_boxes: list, p) -> int:
        """本列 DP 结果里「一字两格」的对数（块 D）：正文格墨迹框映回原图（左上原点）后交给 yolo_merge_pairs。"""
        wr = wins.column(col)
        if wr is None:
            return 0
        mp = ColumnMapper(page_w, wr.left_line.to_vline(), wr.right_line.to_vline(), wr.top_y, wr.bottom_y)
        ink = []
        for c in sorted((c for c in r.cells if c.kind == "char"), key=lambda c: c.y0):
            ib = _ink_box(img, c, p.ink_threshold)
            if ib is None:
                ink.append(None)
                continue
            bx0, by0, bx1, by1 = mp.bbox_tr(*ib)
            ink.append((page_w - 1 - bx1, by0, page_w - 1 - bx0, by1))   # 规范空间（右上原点）→ 左上原点
        return yolo_merge_pairs(ink, yolo_boxes, p.yolo_cover, p.yolo_max_h)

    # ── 职名页分支 ────────────────────────────────────────────────────
    def _run_roster(self, ctx: RunContext, p: RowSegmentParams, page: int,
                    gate: GateManifest, wins: PageWindows, only: set[int] | None = None) -> PageCells:
        """职名页：每列字数不定，`n_body_slots` = 本列实际位数，`boundaries` 为空（没有格线）。

        雙行小字配对成同一物理位：右行第 i 字（jiazhu_a）与左行第 i 字（jiazhu_b）共用 pos，
        `gap_center` = 两行之间的缝——Step4 按 pos 合成满宽格再从缝拆开，与正文雙行同一条路。
        列级 flags 一律带 `roster`（闸3 据此不按版式格数拦）；字数是推出来的列另带
        `roster_dense_guess`，相邻字 y 重叠的带 `roster_overlap`（见 books/siku_zongmu/roster_segment）。"""
        # 职名页的实现按册的套书选（core/seg_set.OVERRIDES）：史記写本用 books/shiji_wyg 自己的，别的书用殿本的
        import importlib
        from ..core.seg_set import resolve
        _impl = lambda name: importlib.import_module(resolve(ctx.book, f"open_guji_cv.books.siku_zongmu.{name}"))  # noqa: E731
        load_scorer = _impl("roster_glyph").load_scorer
        segment_roster_page = _impl("roster_segment").segment_roster_page
        page_w = wins.page_size[0]
        admitted = [gc for gc in gate.columns if (gc.admitted or not p.only_admitted)
                    and (only is None or gc.col in only)]
        imgs = [(ctx.image("column_image", column_key(page, gc.col)), gc.content_x) for gc in admitted]
        scorer = None
        if p.roster_glyph_refine:
            # 库缺失/为空时 scorer 为 None → 只走几何切分，不报错（职名页本来就有人核兜底）
            scorer = load_scorer(p.roster_glyph_db, p.roster_glyph_fingerprint)
        kw = {}
        ref_lines_of = getattr(_impl("roster_segment"), "page_ref_lines", None)
        if p.roster_ref_corpus and p.roster_ref_pins and ref_lines_of is not None:
            from ..core.workspace import corpus_path
            refs = ref_lines_of(corpus_path(p.roster_ref_corpus), corpus_path(p.roster_ref_pins), ctx.book.id, page)
            if refs is not None:
                kw["refs"] = [refs.get(gc.col) for gc in admitted]
                # 按整理本重切前先丢印里的块（同下面切完后的印过滤）：印文笔画会被数成字，字数就对不上
                seals_pre = _page_seals(ctx, page)
                drops = []
                for gc, (im, _cx) in zip(admitted, imgs):
                    wrec = wins.column(gc.col)
                    mp = (None if wrec is None else
                          ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                       wrec.top_y, wrec.bottom_y))
                    drops.append(_in_seal(seals_pre, mp, im, p.ink_threshold))
                kw["drops"] = drops
        results = dict(zip((gc.col for gc in admitted),
                           segment_roster_page(imgs, ink_threshold=p.ink_threshold, scorer=scorer, **kw)))
        col_img = {gc.col: im for gc, (im, _cx) in zip(admitted, imgs)}
        seals = _page_seals(ctx, page)
        out: list[ColumnCells] = []
        for gc in gate.columns:
            if only is not None and gc.col not in only:
                continue
            base = dict(col=gc.col, n_raised=0, period=gate.period, ref_w=gate.ref_w,
                        content_x=gc.content_x, border_top=gc.border_top,
                        border_bottom=gc.border_bottom, top_slack=0.0)
            if gc.col not in results:
                out.append(ColumnCells(ok=False, n_body_slots=0,
                                       error="未过交接闸: " + "; ".join(gc.reject), **base))
                continue
            rc = results[gc.col]
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            # 落在印里的字丢掉（同正文列端表空格认印，读 seals 产物）：印文笔画会被当成一串字
            in_seal = _in_seal(seals, mapper, col_img[gc.col], p.ink_threshold)
            if in_seal is not None:
                rc.items = [it for it in rc.items if not in_seal(it)]
            # 物理位：正文字各占一位；雙行按「右行第 i 字 ↔ 左行第 i 字」配对共占一位
            pos_of: list[int] = []
            gap_of: list[float | None] = []
            pos, i, items = 0, 0, rc.items
            while i < len(items):
                if items[i].kind != "jiazhu_a":
                    pos += 1
                    pos_of.append(pos)
                    gap_of.append(None)
                    i += 1
                    continue
                j = i
                while j < len(items) and items[j].kind == "jiazhu_a":
                    j += 1
                k = j
                while k < len(items) and items[k].kind == "jiazhu_b":
                    k += 1
                a_run, b_run = items[i:j], items[j:k]
                gap = (min(it.x0 for it in a_run) + max((it.x1 for it in b_run),
                                                        default=min(it.x0 for it in a_run))) / 2.0
                n_pair = max(len(a_run), len(b_run))
                for n in range(len(a_run)):
                    pos_of.append(pos + 1 + n)
                    gap_of.append(gap)
                for n in range(len(b_run)):
                    pos_of.append(pos + 1 + n)
                    gap_of.append(gap)
                pos += n_pair
                i = k
            cells: list[CellRec] = []
            for order, (it, ps, gp) in enumerate(zip(items, pos_of, gap_of)):
                cells.append(CellRec(
                    slot=ps, pos=ps, y0=float(it.y0), y1=float(it.y1),
                    x0=float(it.x0), x1=float(it.x1), kind=it.kind,
                    sub={"jiazhu_a": "a", "jiazhu_b": "b"}.get(it.kind), order=order,
                    gap_center=gp, raised=False,
                    flags=["dense_guess"] if it.dense_guess else [],
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2))
                                for x, y in mapper.quad_tr(it.x0, it.y0, it.x1, it.y1)]),
                ))
            out.append(ColumnCells(ok=True, n_body_slots=pos, cells=cells, boundaries=[],
                                   em=float(rc.em), flags=["roster", *rc.flags], **base))
        return PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)


def _apply_manual_cells(pc: PageCells, manual: dict[int, list[dict]], gate: GateManifest,
                        wins: PageWindows) -> PageCells:
    """人工指定的整列格（`lookup.resolved_manual_cells`）替换算法切出的那一列。

    与职名页同一套下游约定：列级 flags 带 `roster`（闸3 不按版式格数拦、Step4 不按格线裁）加 `manual_cells`，
    `boundaries` 为空；雙行 a/b 同 slot 共 pos，`gap_center` = 两行之间的缝。未过交接闸的列不动。"""
    if not manual:
        return pc
    page_w = wins.page_size[0]
    cols = []
    for cc in pc.columns:
        spec = manual.get(cc.col)
        gc = next((g for g in gate.columns if g.col == cc.col), None)
        if spec is None or gc is None:
            cols.append(cc)
            continue
        wrec = wins.column(cc.col)
        mapper = None
        if wrec is not None:
            mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                  wrec.top_y, wrec.bottom_y)
        a_x = [c["x0"] for c in spec if c.get("sub") == "a"]
        b_x = [c["x1"] for c in spec if c.get("sub") == "b"]
        gap = (min(a_x) + max(b_x)) / 2.0 if a_x and b_x else None
        cells: list[CellRec] = []
        for order, c in enumerate(spec):
            kind = c.get("kind") or "char"
            cells.append(CellRec(
                slot=int(c["slot"]), pos=int(c["slot"]), y0=float(c["y0"]), y1=float(c["y1"]),
                x0=float(c["x0"]), x1=float(c["x1"]), kind=kind, sub=c.get("sub"), order=order,
                gap_center=gap if kind.startswith("jiazhu") else None, raised=False,
                flags=["manual"],
                quad_page=(None if mapper is None else
                           [(round(x, 2), round(y, 2))
                            for x, y in mapper.quad_tr(c["x0"], c["y0"], c["x1"], c["y1"])])))
        n_pos = len({c.pos for c in cells})
        cols.append(ColumnCells(
            ok=True, n_body_slots=n_pos, cells=cells, boundaries=[], em=None,
            flags=["roster", "manual_cells"], col=cc.col, n_raised=0, period=gate.period,
            ref_w=gate.ref_w, content_x=gc.content_x, border_top=gc.border_top,
            border_bottom=gc.border_bottom, top_slack=0.0))
    return PageCells(page=pc.page, period=pc.period, ref_w=pc.ref_w, columns=cols)


def _shift_occ(occ: set, d: int, n_body: int) -> set | None:
    """表的字格整体挪 d 格（只挪正文格号；抬头格、挪出 1..n_body 的不挪，返回 None）。"""
    body = {s for s in occ if s > 0}
    if not body or any(s < 0 for s in occ) or not all(1 <= s + d <= n_body for s in body):
        return None
    return {s + d for s in body}


def _shift_lay(lay: dict, d: int) -> dict:
    return dict(lay, **{k: [s + d for s in lay.get(k, ())] for k in ("slots", "notes", "half")})


def _reraise(lay: dict, n_raised: int) -> dict:
    """格位表一行按人裁抬头级数重编格号：表的字按列内先后不动，整体挪到 `n_raised` 级抬头的格号上。

    表的抬头级数来自整理本，有的列整理本没标抬头（殿本换图源 vol35 p59 c5、vol36 p51 c4、vol28 p28 c7：
    表记不抬头、首字在 1 号格），人裁说抬一格时首字其实在 -1 号格。只把抬头位记成有字、其余格号照表，
    整列就多出一个字格，落在列末空白上（切出空格或噪点，2026-10-27 A31 报）。"""
    r = int(lay.get("raised", 0))
    if r == n_raised:
        return lay

    def mv(s: int) -> int:
        pos = _slot_to_pos(s, r)
        return pos - n_raised - 1 if pos <= n_raised else pos - n_raised

    return dict(lay, raised=n_raised, **{k: [mv(s) for s in lay.get(k, ())] for k in ("slots", "notes", "half")})


def _slot_to_pos(slot: int, n_raised: int) -> int:
    """对外 slot（正文 1..n，抬头 -n_raised..-1，跳 0）→ 1 起的物理位置。"""
    return slot + n_raised + 1 if slot < 0 else slot + n_raised
