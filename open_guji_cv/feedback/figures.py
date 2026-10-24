"""图片格与插图块的人裁读出（GUJI-740，2026-10-24）：Step9 导出写 char `fig`、cord `marks.figure`、fig.json 用。

设计见 book-text `docs/design/2026-10-图片格与插图设计.md` §五，格式见 guji-format spec 09（guji-fig v0.1）。

两种图，两条来路：

| | 人怎么定 | 事件 | 落到哪 | 本模块 |
|---|---|---|---|---|
| **图片格**（一格是图形，不是字） | 定字台／网站精校票 `choice=figure` | `confirm`，`payload.v="figure"`、`alt` | `crop_exclude` 进排除名单，理由 `figure`；Step7 照排除格处理（不进库、不出卡），`report/slots` 占位出 □ | `figure_cells` |
| **插图块**（占几列、半页、整页） | 控制台在页上画框 | `figure_region`（页级，一页一条，后到覆盖） | 不配消费者，不让产物过期 | `resolved_figure_regions` |

`figure_region` 的单位键 `figure:<册>:<页>`，payload：

    {"regions": [{"box": [x, y, w, h], "col": 3, "span": 4, "alt": "河圖", "fig": "p52-fig1"}, …]}

- `box`：canvas 像素（与 book-text cord 同一坐标），左上原点；
- `col`：图块右边第一列的列号（cv 物理列号，同格位 key 的「列」）；`span`：占几列（缺省 1）；
- `alt`：说明，可空（导出写「图形符号」）；`fig`：图 id，可空（导出按 `p<页>-fig<n>` 起）；
- 同一页再画一次就整页覆盖；`regions: []` 撤掉本页全部插图块。
"""
from __future__ import annotations

from pathlib import Path

#: 人定是图时没写说明的，导出写这个（spec 09 §3.2）
DEFAULT_ALT = "图形符号"


def _alt_of(rec: dict) -> str:
    for tag in rec.get("evidence") or []:
        if isinstance(tag, str) and tag.startswith("alt="):
            return tag[4:]
    return ""


def figure_cells(book: str, exclusions_path: str | Path | None = None, log=None) -> dict[str, str]:
    """本册判成图片格的格 → 说明：`{裸 id（vol05:148:2:14）: alt}`（没写说明的是空串）。

    「是不是图」以排除名单为准（Step7、`report/slots` 读的就是它，三处同口径）；说明取这一格最新一条
    `v=figure` 事件的 `alt`（后来改过说明的以事件为准），没有事件可读时取名单 evidence 里的 `alt=`。"""
    from ..clustering.exclusions import default_path, load_exclusions
    pre = f"{book}:"
    ex = load_exclusions(str(exclusions_path) if exclusions_path else default_path())
    out = {k: _alt_of(r) for k, r in ex.items() if k.startswith(pre) and r.get("reason") == "figure"}
    if not out:
        return out
    from .events import EventLog, counts_as_human, iter_events_readonly, replay_key
    try:
        evs = sorted(iter_events_readonly(log or EventLog()), key=replay_key)
    except FileNotFoundError:
        return out
    for e in evs:
        if e.kind != "confirm" or e.target.key not in out or not counts_as_human(e):
            continue
        p = e.payload or {}
        if p.get("v") == "figure" and p.get("alt"):
            out[e.target.key] = str(p["alt"])
    return out


def region_key(book: str, page: int) -> str:
    return f"figure:{book}:{page}"


def resolved_figure_regions(book: str, log=None) -> dict[int, list[dict]]:
    """本册各页的插图块：`{页: [{box, col, span, alt, fig?}, …]}`。每页取最新一条 `figure_region`。"""
    from .events import EventLog, counts_as_human, iter_events_readonly, replay_key
    try:
        evs = sorted(iter_events_readonly(log or EventLog()), key=replay_key)
    except FileNotFoundError:
        return {}
    pre = f"figure:{book}:"
    last: dict[int, list[dict]] = {}
    for e in evs:
        if e.kind != "figure_region" or not e.target.key.startswith(pre) or not counts_as_human(e):
            continue
        tail = e.target.key[len(pre):]
        if not tail.isdigit():
            continue
        regs = []
        for r in (e.payload or {}).get("regions") or []:
            box = r.get("box")
            if not (isinstance(box, list) and len(box) == 4 and isinstance(r.get("col"), int)):
                raise ValueError(f"{e.id}：插图块要有 box=[x,y,w,h] 与整数 col，收到 {r}")
            regs.append({"box": [float(v) if not float(v).is_integer() else int(v) for v in box],
                         "col": int(r["col"]), "span": int(r.get("span") or 1), "alt": str(r.get("alt") or ""),
                         **({"fig": str(r["fig"])} if r.get("fig") else {})})
        last[int(tail)] = sorted(regs, key=lambda r: r["col"])
    return {pg: regs for pg, regs in sorted(last.items()) if regs}


# ───────────────────────── 控制台画框（GUJI-737 收尾，2026-10-24） ─────────────────────────
# 控制台「插图块」卡：人在页图上拖框，后端按本页各列的横向范围算出 `col`／`span`，校验后写一条 `figure_region`。
# 坐标一律是 canvas 像素（左上原点，同 book-text cord）；cv 产物是右上原点，这里换算（`formats.guji_page.tr_bbox_to_xywh`）。

#: 框盖住一列宽度的多少算「占了这一列」
COL_COVER = 0.5


def page_columns(store, book: str, page: int) -> tuple[int, int, list[dict]]:
    """本页尺寸与各列横向范围：`(W, H, [{col, x, w}, …])`，列按 `col` 升序。

    范围取 Step4 `cell_shrink` 该列各格字框的并（换成左上原点）；没有字框的列不列（插图页常见，`col` 由人填）。
    尺寸取 Step1 `border_detect`（与导出 `guji_page_cv` 同源）；缺产物抛 `ProductMissing`。"""
    from ..core.spec import page_key
    from ..errors import ProductMissing
    from ..formats.guji_page import tr_bbox_to_xywh
    key = page_key(page)
    bd = store.read_raw(book, "border_detect", key)
    if bd is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 border_detect 产物")
    b = bd["borders"]
    W, H = int(b["width"]), int(b["height"])
    ci = store.read_raw(book, "cell_shrink", key) or {}
    cols = []
    for c in (ci.get("char_index") or {}).get("columns") or []:
        boxes = [tr_bbox_to_xywh(ch["bbox_page"], W) for ch in c.get("chars") or []
                 if ch.get("bbox_page") is not None and ch.get("cell_type") != "empty"]
        if not boxes or not isinstance(c.get("col"), int):
            continue
        x0 = min(bx[0] for bx in boxes)
        x1 = max(bx[0] + bx[2] for bx in boxes)
        cols.append({"col": int(c["col"]), "x": x0, "w": x1 - x0})
    return W, H, sorted(cols, key=lambda c: c["col"])


def columns_for_box(columns: list[dict], box: list) -> tuple[int, int] | None:
    """框占了哪几列：盖住某列宽度 ≥ `COL_COVER` 的算占。返回 `(最小列号, 列数)`；一列都没占 → None。
    占的列号不连续（中间夹着没被盖住的列）→ ValueError（插图块按整列替换，不能跳列）。"""
    x, _, w, _ = (float(v) for v in box)
    hit = []
    for c in columns:
        ov = min(x + w, c["x"] + c["w"]) - max(x, c["x"])
        if c["w"] > 0 and ov / c["w"] >= COL_COVER:
            hit.append(c["col"])
    if not hit:
        return None
    hit.sort()
    if hit != list(range(hit[0], hit[0] + len(hit))):
        raise ValueError(f"框占的列不连续：{hit}")
    return hit[0], len(hit)


def normalize_regions(regions: list[dict], columns: list[dict], W: int, H: int) -> list[dict]:
    """控制台交来的一页插图块 → `figure_region` payload 的 `regions`（同 `resolved_figure_regions` 的形状）。

    - `box` 四个数、宽高为正，裁到页内（取整）；
    - 没给 `col` 就按框算（`columns_for_box`），算不出（这几列没字框）就报错让人填；给了 `col` 没给 `span`，从这列数到框盖住的最左一列，算不出取 1；
    - `alt` 去空白、限 60 字（同网站精校卡）；`fig` 只许 `[a-z0-9][a-z0-9-]*`；
    - 同页两块占的列不许重叠（导出会拒）。"""
    import itertools
    import re
    out = []
    for i, r in enumerate(regions, 1):
        box = r.get("box")
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            raise ValueError(f"第 {i} 块：box 要是 [x, y, w, h]")
        x, y, w, h = (float(v) for v in box)
        x0, y0 = max(0, round(x)), max(0, round(y))
        x1, y1 = min(W, round(x + w)), min(H, round(y + h))
        if x1 - x0 < 4 or y1 - y0 < 4:
            raise ValueError(f"第 {i} 块：框太小或在页外")
        nb = [x0, y0, x1 - x0, y1 - y0]
        col, span = r.get("col"), r.get("span")
        auto = columns_for_box(columns, nb)
        if col in (None, ""):
            if auto is None:
                raise ValueError(f"第 {i} 块：这几列没有字框，算不出占哪几列，请填列号和列数")
            col, span = auto
        elif span in (None, ""):          # 手填了列号：从这一列数到框盖住的最左一列
            lo = int(col)
            span = auto[0] + auto[1] - lo if auto is not None and auto[0] <= lo < auto[0] + auto[1] else 1
        col, span = int(col), int(span)
        if col < 1 or span < 1:
            raise ValueError(f"第 {i} 块：列号、列数要是正整数")
        alt = str(r.get("alt") or "").strip()
        if len(alt) > 60:
            raise ValueError(f"第 {i} 块：说明超过 60 字")
        fig = str(r.get("fig") or "").strip()
        if fig and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", fig):
            raise ValueError(f"第 {i} 块：图 id 只许小写字母、数字和连字符：{fig!r}")
        out.append({"box": nb, "col": col, "span": span, "alt": alt, **({"fig": fig} if fig else {})})
    out.sort(key=lambda r: r["col"])
    for a, b in itertools.pairwise(out):
        if b["col"] < a["col"] + a["span"]:
            raise ValueError(f"两块插图占的列重叠：列 {a['col']}–{a['col'] + a['span'] - 1} 与列 {b['col']} 起")
    return out
