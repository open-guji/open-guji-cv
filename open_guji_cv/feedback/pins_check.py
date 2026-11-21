"""推格级钉子（manual-cells）前的预检：会不会切对、哪些人裁会失锚、该补什么锚（A22 F3，2026-11-10）。

设计：Claude Doc《切分框架改进详细设计（F1–F8）》F3 节；命令 `scripts/seg_pins_check.py`。

## 为什么要它

钉子一改，格号或格框就变。老人裁事件没有锚、补锚档里也没有墨框时，绑定要拿**现格字块图**去比；
执行机拿不到新格的字块图（缓存里没有、`GUJI_BINDINGS_NO_RENDER`），于是行里记 `why=no_patch`，
`lookup.human_chars` 整册报错、seed_admit 失败（史記 04 #1746、06 #1747）。另一种是 cell_shrink
用旧格线判空，钉子写了字的格静默变成空格（史記 r16 丢 12 字）。

这两件事推库前在本机就能查出来：

1. **钉子 vs cell_shrink**：钉子列每一格，cell_shrink 都要出同号的字格（不是 empty）。
2. **模拟执行机绑定**：空缓存＋不现切，对涉及页重算绑定，逐条报 valid / rebound / review / void /
   unanchored，标出会让 `human_chars` 报 no_patch 的事件。
3. **补锚草稿**：失锚的老事件，取它在**旧切分**里那一格的页面框当墨框（`ink_bbox`，右上原点，同
   `quad_page`），按 `anchor_backfill.bind_ink` 预演落到新切分哪一格，写成补锚档草稿行。人看图核过才推。
4. **事件 id 重复**：同一 id 出现多次（殿本 vol04/05 迁出人裁去重后拉库 sha 不符）。

本模块只读产物、事件，绑定缓存写到临时目录，不改任何产物、指纹、中心库数据。
"""
from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

import numpy as np

# 绑定状态里「下游会采信」的两种（同 bindings.USE_STATUSES）
USE = ("valid", "rebound")


# ── 1. 钉子对账 ──────────────────────────────────────────────────────────────

def pins_of(items: Iterable, book: str) -> dict[tuple[int, int], list[dict]]:
    """manual-cells 条目（GoldItem 或同形 dict）→ `{(页, 列): cells}`，只取本册 active 的。"""
    out: dict[tuple[int, int], list[dict]] = {}
    for it in items:
        d = it if isinstance(it, dict) else it.model_dump()
        anc = d.get("anchor") or {}
        if d.get("status", "active") != "active" or str(anc.get("book")) != str(book):
            continue
        cells = (d.get("expected") or {}).get("cells")
        if anc.get("page") is None or anc.get("col") is None or not isinstance(cells, list) or not cells:
            continue
        out[(int(anc["page"]), int(anc["col"]))] = cells
    return out


def read_items(path: Path) -> list[dict]:
    """manual-cells 分片文件逐行读成 dict（坏行跳过，格式问题交给 `lookup.check_manual_cells`）。"""
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def diff_pins(old: dict, new: dict) -> dict[tuple[int, int], str]:
    """两份 `pins_of` 结果比：`{(页, 列): added|changed|removed}`，没变的列不列。"""
    out = {}
    for k in set(old) | set(new):
        if k not in old:
            out[k] = "added"
        elif k not in new:
            out[k] = "removed"
        elif _canon(old[k]) != _canon(new[k]):
            out[k] = "changed"
    return dict(sorted(out.items()))


def _canon(cells: list[dict]) -> list:
    return sorted(json.dumps(c, sort_keys=True, ensure_ascii=False) for c in cells)


def pin_slots(cells: list[dict]) -> set[tuple[int, str]]:
    """钉子一列的格号集合 `{(slot, sub)}`。"""
    return {(int(c["slot"]), str(c.get("sub") or "")) for c in cells}


def check_pin_vs_chars(pin: list[dict], col_chars) -> list[str]:
    """钉子列 vs cell_shrink 那一列（`ColumnChars` 或 None）：问题清单，空 = 一致。

    钉子的每一格，cell_shrink 都要有同号的格且 `cell_type == "char"`；cell_shrink 多出的字格也报。"""
    want = pin_slots(pin)
    if col_chars is None:
        return ["cell_shrink 没有这一列"]
    got_char, got_empty = set(), set()
    for ch in col_chars.chars:
        key = (int(ch.slot), str(ch.sub or ""))
        (got_char if ch.cell_type == "char" else got_empty).add(key)
    probs = []
    for s, sb in sorted(want - got_char):
        why = "判成空格（字丢了）" if (s, sb) in got_empty else "没有这一格"
        probs.append(f"钉子 {s}{sb} 在 cell_shrink {why}")
    for s, sb in sorted(got_char - want):
        probs.append(f"cell_shrink 多出字格 {s}{sb}（钉子里没有）")
    return probs


# ── 1c. 整列丢字（SJ r75，2026-11-17）────────────────────────────────────────
# 钉子是整列替换：只写要改的几格，列里其余字整段没了也不报错（史記 r75 28:93:3 只剩 19–21 格）。
# 第一节只比「钉子的格 vs cell_shrink」，钉子本身少写了格它看不出；第 1b 节只看钉子格线压不压墨。这里补两项：
#   ① 钉后格数要等于原列格数（旧切分那一列的有字格；没有旧切分就比旧钉子），不等要在钉子里写理由；
#   ② 列图上格外不能有成段的墨（判据照 SJ 本地扫描：每行墨 ≥4px、连续 ≥25px、不在任一格内），
#      列端框线（版框线附近、剥掉的长直线）、印章（seal_detect 印框压到的段，只当提示）除外。

COUNT_WHY_KEY = "count_why"   # 钉子 expected 里写「格数为什么和原列不同」（不进指纹，row_segment 只读 cells）
UNCOV_ROW_PX = 4              # 一行（文字带内、剥掉长直线后）墨 ≥ 这么多像素算有墨行
UNCOV_SEG_PX = 25             # 连续有墨行 ≥ 这么多 px，
UNCOV_SEG_FRAC = 0.4          # 且 ≥ 参照字高 × 这么多（殿本 vol07 全册 1179 列自动切：0.25 时有 3 列是列端字脚＋框线残点 29–39px，0.4 时 0；史記丢字段最矮 0.53）
UNCOV_BORDER_NEAR = 0.2       # 离上／下版框线这么多格高以内的不算（列端框线、框线毛边）


def pin_notes(items: Iterable, book: str) -> dict[tuple[int, int], str]:
    """manual-cells 条目 → `{(页, 列): expected.count_why}`（只取本册 active 且写了理由的）。"""
    out = {}
    for it in items:
        d = it if isinstance(it, dict) else it.model_dump()
        anc = d.get("anchor") or {}
        if d.get("status", "active") != "active" or str(anc.get("book")) != str(book):
            continue
        why = str((d.get("expected") or {}).get(COUNT_WHY_KEY) or "").strip()
        if why and anc.get("page") is not None and anc.get("col") is not None:
            out[(int(anc["page"]), int(anc["col"]))] = why
    return out


def text_slots(col_cells) -> set[tuple[int, str]]:
    """一列（`ColumnCells`）有字格的格号 `{(slot, sub)}`（blank 不算）。"""
    return {(int(c.slot), str(c.sub or "")) for c in col_cells.cells if c.kind != "blank"}


def check_pin_count(pin: list[dict], old_col=None, old_pin: list[dict] | None = None, why: str = "") -> dict | None:
    """① 钉后格数 vs 原列格数 → `{"block", "note", "new", "old"}`；一样 → None。

    原列：旧切分（row_segment）那一列的有字格；旧切分没有这一列（或无解）就比旧钉子；都没有只出提示。
    格数不同但钉子写了 `expected.count_why` → 提示（理由照抄进报告）；没写 → 问题。"""
    n_new = len(pin_slots(pin))
    if old_col is not None and old_col.ok and old_col.cells:
        n_old, src = len(text_slots(old_col)), "旧切分"
    elif old_pin:
        n_old, src = len(pin_slots(old_pin)), "旧钉子"
    else:
        return {"block": False, "new": n_new, "old": None, "note": f"钉后 {n_new} 格；没有旧切分或旧钉子可比，格数没查"}
    if n_new == n_old:
        return None
    note = f"钉后 {n_new} 格，{src}这一列 {n_old} 格（{n_new - n_old:+d}）"
    if why:
        return {"block": False, "new": n_new, "old": n_old, "note": f"{note}，理由：{why}"}
    return {"block": True, "new": n_new, "old": n_old,
            "note": f"{note}，钉子没写理由（expected.{COUNT_WHY_KEY}）。钉子是整列替换，只写要改的几格，"
                    f"其余字会整段丢掉；从现役 row_segment 抽整列再改（`guji seg pin` 起稿就是整列），"
                    f"真要改格数就在钉子里写理由"}


def uncovered_ink(gray: np.ndarray, col_cells, ref_h: float | None = None, *, seal_spans=(),
                  ink_threshold: int = 128) -> list[dict]:
    """② 列图上不在任何有字格里的成段墨 → `[{"y0", "y1", "h", "ink", "seal"}]`（列图坐标）。

    文字带取 `content_x`（没有就取各格 x 范围），先剥长直线（界行、版框横线，同 `seg_screen.strip_long_lines`）；每行墨 ≥ UNCOV_ROW_PX、
    不在任何有字格的 y 范围内算格外墨行；连续段高 ≥ max(UNCOV_SEG_PX, UNCOV_SEG_FRAC × 参照字高) 才报。
    细高的连通块（界行残段，`_drop_rule_bits`）也去掉。版框线（`border_top`／`border_bottom`）以外和离它 UNCOV_BORDER_NEAR 格高以内的不算（列端框线）。
    `seal_spans`：印框压到的列图 y 段，段与之相交的 `seal=True`（调用方当提示）。"""
    body = [c for c in col_cells.cells if c.kind != "blank"]
    if not body:
        return []
    h, w = gray.shape[:2]
    if col_cells.content_x:
        x0, x1 = int(col_cells.content_x[0]), int(col_cells.content_x[1])
    else:
        x0, x1 = int(min(c.x0 for c in body)), int(max(c.x1 for c in body))
    x0, x1 = max(0, x0), min(w, max(x1, x0 + 1))
    from ..seg.rules import strip_long_rules

    # 剥线参数同 seg_screen.strip_long_lines（SJ 快筛 ORPH）
    ink = strip_long_rules((gray[:, x0:x1] < ink_threshold).astype(np.uint8), vline=200, hline_frac=0.85, hline_min=40)
    ink = _drop_rule_bits(ink)
    row = ink.sum(axis=1)
    covered = np.zeros(h, dtype=bool)
    for c in body:
        covered[max(0, int(np.floor(c.y0))):min(h, int(np.ceil(c.y1)))] = True
    ref = float(ref_h or col_cells.period or 0.0)
    near = UNCOV_BORDER_NEAR * ref
    lo = 0 if col_cells.border_top is None else max(0, int(np.ceil(col_cells.border_top + near)))
    hi = h if col_cells.border_bottom is None else min(h, int(np.floor(col_cells.border_bottom - near)))
    inky = (row >= UNCOV_ROW_PX) & ~covered
    inky[:lo] = False
    inky[max(hi, 0):] = False
    min_h = max(UNCOV_SEG_PX, UNCOV_SEG_FRAC * ref)
    out = []
    y = 0
    while y < h:
        if not inky[y]:
            y += 1
            continue
        e = y
        while e < h and inky[e]:
            e += 1
        if e - y >= min_h:
            seal = any(a < e and b > y for a, b in seal_spans)
            out.append({"y0": y, "y1": e, "h": e - y, "ink": int(row[y:e].sum()), "seal": seal})
        y = e
    return out


UNCOV_RULE_W = 25             # 连通块宽 ≤ 这么多 px 且 ≤ 高 × UNCOV_RULE_RATIO：界行／竖框线残段（不到 200px 没被剥掉），
UNCOV_RULE_RATIO = 0.3        # 同 seg_screen.orphan_ink「界行残段」（史記 01:108:1 列尾一截竖线）


def _drop_rule_bits(ink: np.ndarray) -> np.ndarray:
    """去掉细高的连通块（界行、竖框线没剥干净的残段）。字的竖笔连着别的笔画，整块不会这么细。"""
    import cv2
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    drop = [i for i in range(1, n)
            if st[i, cv2.CC_STAT_WIDTH] <= UNCOV_RULE_W and st[i, cv2.CC_STAT_WIDTH] <= UNCOV_RULE_RATIO * st[i, cv2.CC_STAT_HEIGHT]]
    if not drop:
        return ink
    out = ink.copy()
    out[np.isin(lab, drop)] = 0
    return out


def seal_spans_col(col_cells, seals) -> list[tuple[float, float]]:
    """印框（`Seal.bbox`，规范空间）换成这一列列图上的 y 段。

    用本列各格的 `quad_page` 拟一条列图 y → 页 y 的直线（列图是竖直拉直的一列，近似线性）；印框 x 范围与本列不相交的不算。
    格没有 `quad_page` 时不能换算：有印就整列算压印（返回 [(-inf, inf)]）。"""
    if not seals:
        return []
    pts, xs = [], []
    for c in col_cells.cells:
        if c.quad_page:
            q = np.asarray(c.quad_page, dtype=float)
            pts += [(c.y0, q[:, 1].min()), (c.y1, q[:, 1].max())]
            xs += [q[:, 0].min(), q[:, 0].max()]
    if len(pts) < 2:
        return [(float("-inf"), float("inf"))]
    a = np.asarray(pts, dtype=float)
    if np.ptp(a[:, 0]) < 1:
        return [(float("-inf"), float("inf"))]
    k, b = np.polyfit(a[:, 0], a[:, 1], 1)
    cx0, cx1 = min(xs), max(xs)
    out = []
    for s in seals:
        sx0, sy0, sx1, sy1 = s.bbox
        if sx1 < cx0 or sx0 > cx1 or abs(k) < 1e-6:
            continue
        ya, yb = sorted(((sy0 - b) / k, (sy1 - b) / k))
        out.append((ya, yb))
    return out


# ── 2. 模拟执行机绑定 ────────────────────────────────────────────────────────

@contextmanager
def executor_like(tmp: Path):
    """空字块缓存＋不现切＋绑定缓存写临时目录：照执行机的条件算绑定，不碰本机缓存。"""
    from . import bindings
    tmp = Path(tmp)
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    keep = {k: os.environ.get(k) for k in ("GUJI_CACHE_DIR", "GUJI_BINDINGS_NO_RENDER")}
    old_dir = bindings._bindings_dir
    os.environ["GUJI_CACHE_DIR"] = str(tmp / "cache")
    os.environ["GUJI_BINDINGS_NO_RENDER"] = "1"
    bindings._bindings_dir = lambda book: tmp / "bindings" / book      # type: ignore[assignment]
    bindings._MEMO.clear()
    bindings._PAGE_MEMO.clear()
    try:
        yield
    finally:
        bindings._bindings_dir = old_dir                               # type: ignore[assignment]
        bindings._MEMO.clear()
        bindings._PAGE_MEMO.clear()
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def old_char(seed_page, cell_key: str) -> str | None:
    """旧产物 seed_admit 这一页里某格定的字（核对草稿的旧格是不是人裁的那个字）；读不到 → None。"""
    if seed_page is None:
        return None
    for col in getattr(seed_page, "columns", []) or []:
        for ch in getattr(col, "chars", []) or []:
            if getattr(ch, "id", None) == cell_key:
                return getattr(ch, "char", None)
    return None


def classify_row(row: dict) -> str:
    """绑定行 → 预检结论：

    - ok：下游照用；
    - unbound：失锚——执行机上有当时字块图的会让 human_chars 报 no_patch、seed_admit 整册失败，
      没有图的悄悄丢掉这条人裁（本机没拉字形库时两种分不开，一律算这一类，都要补锚）；
    - lost：锚还在、但对不上了（切开、合并、格没了：review／void），不采信、回待审。"""
    st = row.get("status")
    if st in USE or (st == "unanchored" and row.get("bound")):
        return "ok"
    if row.get("why") == "no_patch" or st == "unanchored":
        return "unbound"
    return "lost"


def split_preexisting(probs: list[str], in_cols: set[str], old_rows: dict[str, dict]) -> tuple[list[str], set[str]]:
    """有问题的绑定分成（本次要管的, 老失锚）。老失锚＝不在改动列、旧切分下也没绑上（`classify_row` 不是 ok）：
    推不推这次钉子都一样，单列出来、不计入预检结论（SJ 11-10，01 p59 四条老 unanchored/review）。
    没有旧切分的（`old_rows` 里没有这条）照旧算本次的。"""
    pre = {e for e in probs if e not in in_cols and e in old_rows and classify_row(old_rows[e]) != "ok"}
    return [e for e in probs if e not in pre], pre


def simulate_bindings(book: str, pages: list[int], tmp: Path, store=None) -> dict[str, dict]:
    """照执行机条件重算这些页的绑定：`{event_id: row}`。`store`：新切分所在产物仓（缺省本机）。"""
    from .bindings import book_bindings
    with executor_like(tmp):
        return book_bindings(book, store=store, refresh=True, pages=sorted(set(pages)))


# ── 3. 补锚草稿 ──────────────────────────────────────────────────────────────

def cell_boxes(page_cells) -> dict[tuple[int, int, str], list[float]]:
    """`PageCells` → `{(col, slot, sub): 页面框}`（右上原点，同 `quad_page`）。"""
    from .anchor import quad_bbox
    out = {}
    for cc in page_cells.columns:
        for c in cc.cells:
            if c.quad_page:
                out[(cc.col, c.slot, c.sub or "")] = list(quad_bbox(c.quad_page))
    return out


def propose_anchor(event_key: str, event_id: str, old_boxes: dict, new_cells, old_bound: str | None = None) -> dict | None:
    """失锚事件 → 补锚草稿行；旧切分里找不到这一格 → None。

    墨框取旧切分里**这条人裁当时绑到的格**（`old_bound`：照执行机条件在旧切分上算的绑定）的页面框，不按事件的格号取——
    换过钉子的列格号会挪，按号取会把字裁到别的字上（SJ 11-10：01:49:4「務」落到「府」）。
    没给 `old_bound` 才退回按事件格号。按 `bind_ink` 预演落到新切分哪一格。"""
    from .anchor import parse_cell_key
    from .anchor_backfill import bind_ink
    from .bindings import _cell_index
    pk = parse_cell_key(old_bound or event_key)
    if pk is None:
        return None
    _book, page, col, slot, sub = pk
    box = old_boxes.get((col, slot, sub or ""))
    if box is None:
        return None
    cell, ins, second = bind_ink(box, _cell_index(new_cells))
    if cell is None:
        pred, to = "review", None
    else:
        to = f"{_book}:{page}:{cell[0]}:{cell[1]}{cell[2]}"
        pred = "valid" if to == event_key else "rebound"
    return {"event": event_id, "key": event_key,
            "anchor": {"ink_bbox": [round(v, 2) for v in box], "source": "backfill:ink"},
            "evidence": {"by": "seg_pins_check", "pred": pred, "to": to, "old_cell": old_bound or event_key,
                         "inside": round(ins, 3), "second": round(second, 3)}}


# ── 4. 事件 id 重复 ──────────────────────────────────────────────────────────

def duplicate_event_ids(events: Iterable) -> dict[str, int]:
    """同一事件 id 出现多次的 `{id: 次数}`。"""
    c = Counter(getattr(e, "id", None) or (e.get("id") if isinstance(e, dict) else None) for e in events)
    c.pop(None, None)
    return {k: n for k, n in c.items() if n > 1}


def duplicate_anchor_keys(lines: Iterable[str]) -> dict[tuple[str, str], int]:
    """补锚档里 (event, key) 出现多次的 `{(event, key): 次数}`。中心库 anchors 表唯一键是 (src_path, event, key)，
    重复行推上去还原 sha 对不上、全员 db pull 失败（SJ 11-10，rev 957044）。"""
    c: Counter = Counter()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        c[(d.get("event"), d.get("key"))] += 1
    return {k: n for k, n in c.items() if n > 1}


def merge_anchor_drafts(lines: list[str], drafts: list[dict]) -> tuple[list[str], set[str]]:
    """把草稿并进补锚档原有各行：事件已有锚行的**原地替换**（一事件一行，`load_backfill` 也是按事件取），
    没有的追加到末尾。返回（并好的各行，被替换的事件 id）。"""
    by_ev = {d["event"]: d for d in drafts}
    out, replaced = [], set()
    for line in lines:
        if not line.strip():
            continue
        ev = json.loads(line).get("event")
        if ev in by_ev:
            if ev not in replaced:
                out.append(json.dumps(by_ev[ev], ensure_ascii=False))
                replaced.add(ev)
            continue        # 同一事件原有多行的，只留替换后那一行
        out.append(line.rstrip("\n"))
    out += [json.dumps(d, ensure_ascii=False) for d in drafts if d["event"] not in replaced]
    return out, replaced


# ── 5. 沙箱重跑（不碰本机产物与缓存）──────────────────────────────────────────

#: 沙箱重跑的两步（闸 row_segment_gate 跟着 row_segment 自动跑）
RERUN_STEPS = ("row_segment", "cell_shrink")
#: 从本机缓存拷进沙箱的图（列图是 row_segment 的输入；cell_shrink 可选读列原图）
CACHE_KINDS = ("column_image", "column_raw")


def _copy_page_products(src_root: Path, dst_root: Path, book: str, pages: list[int]) -> None:
    """本册各步产物里这些页的 json 与各步 manifest 拷进沙箱（只拷要的页，不整本拷）。"""
    import shutil

    from ..core.spec import page_key
    keys = {page_key(p) for p in pages}
    bdir = Path(src_root) / book
    if not bdir.is_dir():
        return
    for sdir in bdir.iterdir():
        if not sdir.is_dir() or "." in sdir.name:          # 跳过 <step>.bak-* 手工备份
            continue
        out = Path(dst_root) / book / sdir.name
        out.mkdir(parents=True, exist_ok=True)
        for f in sdir.iterdir():
            if f.name.startswith("_manifest") or f.stem in keys or f.stem.split(".")[0] in keys:
                shutil.copy2(f, out / f.name)
        prev = sdir / "_prev"
        if prev.is_dir():
            (out / "_prev").mkdir(exist_ok=True)
            for f in prev.iterdir():
                if f.stem in keys:
                    shutil.copy2(f, out / "_prev" / f.name)


def _copy_page_cache(src_root: Path, dst_root: Path, book: str, pages: list[int]) -> None:
    import shutil
    pre = tuple(f"p{p:04d}" for p in pages)
    for kind in CACHE_KINDS:
        sdir = Path(src_root) / book / kind
        if not sdir.is_dir():
            continue
        out = Path(dst_root) / book / kind
        out.mkdir(parents=True, exist_ok=True)
        for f in sdir.iterdir():
            if f.name.startswith(pre):
                shutil.copy2(f, out / f.name)


@contextmanager
def pins_override(book: str, pins: dict[tuple[int, int], list[dict]] | None):
    """让 row_segment 这次读到的本册钉子换成 `pins`（`None` = 不改；`{}` = 本册一个钉子都不用）。别的册照旧。"""
    from . import lookup
    if pins is None:
        yield
        return
    orig = lookup.resolved_manual_cells

    def fake(b: str):
        return dict(pins) if str(b) == str(book) else orig(b)
    lookup.resolved_manual_cells = fake                      # type: ignore[assignment]
    try:
        yield
    finally:
        lookup.resolved_manual_cells = orig                  # type: ignore[assignment]


def sandbox_rerun(book: str, pages: list[int], tmp: Path, pins: dict | None, log=None):
    """把这些页的产物、列图拷进 `tmp`，在沙箱里从 row_segment 跑到 cell_shrink（钉子换成 `pins`）。

    返回沙箱的 `(ProductStore, ImageCache)`。本机产物、缓存、中心库都不动。"""
    from ..core.book import load_book
    from ..core.engine import Engine
    from ..core.pipeline import default_pipeline_id, load_pipeline
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    tmp = Path(tmp)
    real_store, real_cache = ProductStore(), ImageCache()
    _copy_page_products(real_store.root, tmp / "products", book, pages)
    _copy_page_cache(real_cache.root, tmp / "cache", book, pages)
    _drop_rerun_products(tmp / "products", book, pages)
    store, cache = ProductStore(tmp / "products"), ImageCache(tmp / "cache")
    bk = load_book(book)
    eng = Engine(bk, load_pipeline(default_pipeline_id(bk)), store=store, cache=cache,
                 log=log or (lambda s: None))
    judge_missing(eng.ctx)
    with pins_override(book, pins):
        rep = eng.run(steps=list(RERUN_STEPS), pages=sorted(set(pages)), force=True)
    return store, cache, rep


class SandboxNotReady(RuntimeError):
    """沙箱条件与执行机不一致（缺切点裁判权重、字形库没拉），预检结论不可信，拒跑。"""


def judge_missing(ctx) -> None:
    """row_segment 要用 U-Net 切点裁判、本机却没有权重或 torch → 抛 `SandboxNotReady`。

    没权重时 Step3 静默走旧规则（`seg/cut_select.ckpt_fingerprint` 返回空串），沙箱切出的与执行机不同（SJ 11-10）。"""
    from ..steps.row_segment import RowSegmentStep
    p = ctx.params_for(RowSegmentStep())
    if getattr(p, "cut_judge", None) in ("unet", "unet_f64") and not getattr(p, "judge_fingerprint", ""):
        from ..seg.cut_select import DEFAULT_CKPT
        raise SandboxNotReady(f"row_segment 要用 U-Net 切点裁判，本机缺 torch 或权重 {DEFAULT_CKPT}："
                              "沙箱会按旧规则切、与执行机不一致。先 `guji model fetch -w <工作区>`（不给 -w 按 cv 模型表补 models/）取回权重再跑")


def glyph_db_missing() -> str | None:
    """本机字形库索引 output/glyph.db 不在或没有 instances 表 → 提示文字；好的 → None。"""
    import sqlite3

    from ..core.workspace import glyph_db_path
    path = glyph_db_path()
    if not Path(path).is_file():
        return f"本机没有字形库索引 {path}"
    try:
        con = sqlite3.connect(str(path))
        try:
            ok = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instances'").fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        return f"字形库索引 {path} 打不开（{e}）"
    return None if ok else f"字形库索引 {path} 是空的（没有 instances 表）"


def _drop_rerun_products(root: Path, book: str, pages: list[int]) -> None:
    """沙箱里要重跑的那几步，先删掉拷进来的旧产物：重跑失败时就是「没有产物」，不会拿旧的当新的比（SJ 11-10）。"""
    from ..core.spec import page_key
    keys = {page_key(p) for p in pages}
    for step in (*RERUN_STEPS, "row_segment_gate"):
        d = Path(root) / book / step
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.stem in keys or f.stem.split(".")[0] in keys:
                f.unlink()


def run_failures(rep) -> list[str]:
    """沙箱重跑里失败（含上游缺失被拦）的 `步:页 原因`。"""
    return [f"{o.step}:p{o.page} {o.error or o.status}" for o in getattr(rep, "outcomes", []) or []
            if o.status == "failed"]


# ── 6. 钉子退役（F2）─────────────────────────────────────────────────────────

RETIRE_EDGE = 0.1          # 每格上下沿与钉子差 ≤ 这么多格高算一致
NEAR_EDGE = 0.25           # ≤ 这么多算「接近」


def retire_verdict(pin: list[dict], col_cells) -> dict:
    """钉子一列 vs 不带钉子自动切出的那一列（`ColumnCells`）→ `{"verdict": retire|near|keep, "max_dev", "why"}`。

    retire：格号集合（含 a/b）相同，且每格上下沿差 ≤ `RETIRE_EDGE` 格高；near：格号相同、差 ≤ `NEAR_EDGE`；其余 keep。"""
    if col_cells is None or not col_cells.ok:
        return {"verdict": "keep", "max_dev": None, "why": "自动切这一列无解"}
    auto = {(c.slot, c.sub or ""): c for c in col_cells.cells if c.kind != "blank"}
    want = {(int(c["slot"]), str(c.get("sub") or "")): c for c in pin}
    if set(auto) != set(want):
        miss, extra = sorted(set(want) - set(auto)), sorted(set(auto) - set(want))
        return {"verdict": "keep", "max_dev": None,
                "why": f"格号不同：缺 {len(miss)} 格、多 {len(extra)} 格"}
    period = col_cells.period or 1.0
    dev = max(max(abs(auto[k].y0 - float(want[k]["y0"])), abs(auto[k].y1 - float(want[k]["y1"])))
              for k in want) / period
    v = "retire" if dev <= RETIRE_EDGE else ("near" if dev <= NEAR_EDGE else "keep")
    return {"verdict": v, "max_dev": round(dev, 3), "why": "" if v != "keep" else "格线偏差大"}
