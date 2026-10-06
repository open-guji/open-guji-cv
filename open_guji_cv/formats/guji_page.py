# -*- coding: utf-8 -*-
"""guji-page v0.2：每字带坐标的页面文本——格式本身的工具（与 CV 产物无关）。

规范正本：`doc/formats/guji_page_v0.2.md`；JSON Schema：`formats/guji_page_v0.2.schema.json`
（v0、v0.1 的 schema 留着，旧文件照样能读、能检查、能导出，`upgrade()` 一路升到 0.2）。
这里只放**不依赖任何管线产物**的东西：结构检查、坐标框换算、稳定 ID、IIIF canvas 约定、
导出器（guji-markdown、IIIF 注释与 canvas）、去 ext、册级索引。CV 产物 → 本格式在
`guji_page_cv.py`；yolo_tool 工程文件互转在 `guji_page_yolo.py`。

几条一眼要记住的口径（规范 §2、§3）：

- 坐标：**IIIF canvas 的整数像素**，**左上原点**，框记 `[x, y, w, h]`（与 `#xywh=` 同序）。
  canvas = IA 原叶；合扫页拆开的每一块各是一个 canvas（尺寸 = 裁剪框，原点 = 裁剪框左上角，
  `canvas.source.selector` 记原叶与裁剪框，与 `image.region` 一一对应）。
  CV 内部的右上原点 `raw_page_px@top-right` 只在导出时换一次（`tr_bbox_to_xywh`），格式里不出现。
- 文本流 `text` 是真源：一个元素 = 一个「字元」。v0.2（用户 10-02 裁定）：阙文位放可见的「□」，
  页上稀疏记 `lacuna: [下标…]`；不带标记的「□」是底本真刻的□（或来源站点的□），照录。
  未收字两层：`text` 放近似的已收字，`zi: [{"i", "ids"|"desc", "rel"}]` 记原形与关系。
  v0/v0.1 的阙文是空串 `""`、组字的 IDS 直接放在 `text` 里——`lacuna_set()`/`zi_at()` 按版本读。
  字框 `glyphs[].text = [start, end)` 引用这条流的区间：一框多字 = 区间长 >1，
  一字多框 = 几个框引同一区间，空区间 = 这框还没对上字。
- 阅读顺序 = `text` 的顺序；列的顺序 = `regions[].columns[]` 的顺序；列内 `runs` 首尾相接铺满 `text`。
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

SCHEMA_ID = "guji-page/0.2"
SCHEMA_V01 = "guji-page/0.1"
SCHEMA_V0 = "guji-page/0"
READABLE = (SCHEMA_V0, SCHEMA_V01, SCHEMA_ID)
CANVAS_SCHEMAS = (SCHEMA_V01, SCHEMA_ID)       # 坐标落在 IIIF canvas 上的版本
_FORMATS = Path(__file__).resolve().parents[2] / "formats"
SCHEMA_PATHS = {SCHEMA_V0: _FORMATS / "guji_page_v0.schema.json",
                SCHEMA_V01: _FORMATS / "guji_page_v0.1.schema.json",
                SCHEMA_ID: _FORMATS / "guji_page_v0.2.schema.json"}
SCHEMA_PATH = SCHEMA_PATHS[SCHEMA_ID]
INDEX_SCHEMA_ID = "guji-layout-index/0.1"
INDEX_SCHEMA_PATH = _FORMATS / "guji_layout_index_v0.1.schema.json"

# IIIF 约定（网站总管 overview#357，2026-10-02）
IIIF_BASE = "https://data.kaiyuanguji.com/iiif"
NORM_WHY = ("异体",)                 # 文本总管 #361·4：norm 只管异体→通行字，校勘改字不进这一层
ZI_FORMS = ("ids", "desc")          # 文本总管 #361·7：方位确定写 IDS，拿不准写描述文字
# v0.2（用户 10-02 裁定，#361·3/7/10）
LACUNA_CHAR = "□"                   # 阙文位在 text 里放的可见字符（U+25A1）；页上 lacuna 标出哪些是阙文
ZI_REL = ("异体", "形近", "部件近")   # text 里的近似字与原形的关系
ZI_NO_NEAR = "〓"                   # 还没有近似字（v0.1 升上来的组字、实在找不到近似）时 text 里的占位
CAND_KEYS = ("lib", "ocr", "rare", "ref")   # 候选字：库首位 / OCR 首位 / 5-b 首位 / 整理本字

LANES = ("main", "jz_r", "jz_l", "solo")
REVIEW = ("pending", "auto", "human", "disputed")

# 稳定 ID 承接的几何门槛——与 feedback/bindings.py 同一组数（同一个问题：重切后「还是不是那一格」）
IOU_SAME = 0.85
IOU_OK = 0.6


# ───────────────────────── 坐标 ─────────────────────────

def tr_bbox_to_xywh(bbox_tr, width: int) -> list[int]:
    """CV 规范空间（右上原点，x 向左）的 `[x0,y0,x1,y1]` → 左上原点整数 `[x,y,w,h]`。

    换算沿用 `core/anchor.py` 的像素中心约定 `x_tl = (W-1) - x_tr`；取整**向外**
    （左上 floor、右下 ceil），保证框只会多包一点墨、不会裁掉笔画。
    """
    x0, y0, x1, y1 = (float(v) for v in bbox_tr)
    a, b = (width - 1) - x1, (width - 1) - x0
    l, r = min(a, b), max(a, b)
    t, btm = min(y0, y1), max(y0, y1)
    xi, yi = math.floor(l), math.floor(t)
    return [xi, yi, max(1, math.ceil(r) - xi), max(1, math.ceil(btm) - yi)]


def tr_point_to_tl(pt, width: int) -> list[int]:
    return [int(round((width - 1) - float(pt[0]))), int(round(float(pt[1])))]


def quad_bounds(quad) -> list[float]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return [min(xs), min(ys), max(xs), max(ys)]


def union_xywh(boxes: Iterable[list[int]]) -> list[int] | None:
    bs = [b for b in boxes if b]
    if not bs:
        return None
    x0 = min(b[0] for b in bs)
    y0 = min(b[1] for b in bs)
    x1 = max(b[0] + b[2] for b in bs)
    y1 = max(b[1] + b[3] for b in bs)
    return [x0, y0, x1 - x0, y1 - y0]


def iou(a, b) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = min(ax1, bx1) - max(a[0], b[0])
    ih = min(ay1, by1) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / float(a[2] * a[3] + b[2] * b[3] - inter)


def intersects(a, b) -> bool:
    return iou(a, b) > 0.0


def frame_of(image: dict) -> tuple[list[float], int, int]:
    """一张图在**源图**上占的区域 `[x,y,w,h]` 与它自身的像素宽高。

    `image.region` 缺省 = 整张源图（即这张图就是源图本身，或源图等比缩放）。
    """
    w, h = int(image["width"]), int(image["height"])
    region = image.get("region")
    if region is None:
        src = image.get("source") or {}
        region = [0, 0, src.get("width", w), src.get("height", h)]
    return [float(v) for v in region], w, h


def map_box(box, src_image: dict, dst_image: dict, *, as_int: bool = True):
    """把 `src_image` 像素空间里的框换到 `dst_image` 像素空间。

    两张图须出自**同一张源图**（`source` 相同，或都缺省）：先按 `region` 搬回源图，
    再按目标的 `region` 与缩放搬过去。用途：缩放档（300/1200 px）画框、
    合扫页拆分后网站用的那张裁图与 CV 跑的那张不是同一版裁法（vol03 p107 实例，见样张 README）。
    """
    s_reg, sw, sh = frame_of(src_image)
    d_reg, dw, dh = frame_of(dst_image)
    sx, sy = s_reg[2] / sw, s_reg[3] / sh          # src 像素 → 源图像素
    dx, dy = dw / d_reg[2], dh / d_reg[3]          # 源图像素 → dst 像素
    x, y, w, h = box
    X = ((s_reg[0] + x * sx) - d_reg[0]) * dx
    Y = ((s_reg[1] + y * sy) - d_reg[1]) * dy
    W, H = w * sx * dx, h * sy * dy
    if not as_int:
        return [X, Y, W, H]
    xi, yi = math.floor(X), math.floor(Y)
    return [xi, yi, max(1, math.ceil(X + W) - xi), max(1, math.ceil(Y + H) - yi)]


def scaled_image(image: dict, width: int) -> dict:
    """同一张图的等比缩放档（IIIF `size=width,`）的描述，喂给 `map_box`。"""
    reg, w, h = frame_of(image)
    return {"width": width, "height": int(round(h * width / w)), "region": reg,
            "source": image.get("source")}


# ───────────────────────── IIIF canvas（v0.1） ─────────────────────────

def canvas_id(book_id: str, volume: int, seq: str, base: str = IIIF_BASE) -> str:
    """`<base>/<bookId>/canvas/<册2位>/<页序4位><后缀>`，如 `…/canvas/03/0105c`。"""
    return f"{base.rstrip('/')}/{book_id}/canvas/{int(volume):02d}/{seq}"


def ia_image_id(item: str, leaf: int) -> str:
    """IA 原叶的 IIIF 图像 id（R12 实测可用的写法），当 `canvas.source.id` 的缺省值。"""
    f = f"{item}%2F{item}_tif.zip%2F{item}_tif%2F{item}_{int(leaf):04d}.tif"
    return f"https://iiif.archive.org/image/iiif/3/{f}"


def seq_for_ws_page(ws_page: int, split_rows: list[dict] | None = None) -> tuple[str, dict | None]:
    """工作区页号 → canvas 页序（IA leaf 号 4 位 + 拆块后缀）。

    `split_rows`：该册在「四庫合扫拆页-裁剪框」表里的行（overview 整理总管 `73d3b4be`，
    字段 vol / ia_leaf / canvas_seq / ws_page / xywh / orig_size）。规则照该表 §二：
    拆点 P 之前同号；P..P+3 → 表里那一块；之后 n−3。返回 (页序, 命中的表行或 None)。
    """
    rows = sorted(split_rows or [], key=lambda r: r["ws_page"])
    if not rows:
        return f"{ws_page:04d}", None
    hit = next((r for r in rows if r["ws_page"] == ws_page), None)
    if hit:
        return hit["canvas_seq"], hit
    P, n_blocks = rows[0]["ws_page"], len(rows)
    leaf = ws_page if ws_page < P else ws_page - (n_blocks - 1)
    return f"{leaf:04d}", None


def make_canvas(book_id: str, volume: int, seq: str, *, width: int, height: int,
                source_id: str | None = None, source_size=None, xywh=None,
                base: str = IIIF_BASE) -> dict:
    """v0.1 的 `canvas` 块。拆块页给 `xywh`（在原叶上的裁剪框）与原叶尺寸，生成 `source.selector`。"""
    c = {"id": canvas_id(book_id, volume, seq, base) if book_id and seq else None,
         "seq": seq, "width": int(width), "height": int(height)}
    if xywh is not None:
        x, y, w, h = (int(v) for v in xywh)
        c["source"] = {"id": source_id,
                       "width": int(source_size[0]) if source_size else None,
                       "height": int(source_size[1]) if source_size else None,
                       "selector": {"type": "FragmentSelector", "value": f"xywh={x},{y},{w},{h}"}}
    return c


def selector_xywh(canvas: dict) -> list[int] | None:
    sel = ((canvas or {}).get("source") or {}).get("selector") or {}
    v = sel.get("value", "")
    if not v.startswith("xywh="):
        return None
    return [int(float(t)) for t in v[5:].split(",")]


def canvas_frame(canvas: dict) -> dict:
    """canvas 当成一张「图」的描述（`width/height/region/source`），喂给 `map_box`。"""
    src = (canvas or {}).get("source") or {}
    fr = {"width": canvas["width"], "height": canvas["height"]}
    reg = selector_xywh(canvas)
    if reg is not None:
        fr["region"] = reg
        fr["source"] = {"width": src.get("width"), "height": src.get("height")}
    return fr


def coord_frame(page: dict) -> dict:
    """本页坐标所在的那张「图」：v0.1 是 canvas，v0 是 `image`。"""
    if page.get("schema") in CANVAS_SCHEMAS and page.get("canvas"):
        return canvas_frame(page["canvas"])
    return page["image"]


def remap_geometry(page: dict, src: dict, dst: dict) -> int:
    """把页上全部几何（字框、标记、列框、区框、界行点）从 `src` 帧搬到 `dst` 帧，裁到 dst 图内。

    用在「CV 跑批那张图 ≠ canvas」时（vol03 p107：产物建在旧裁法的图上）。返回被裁过的框数。
    """
    W, H = int(dst["width"]), int(dst["height"])
    clipped = 0

    def mb(b):
        nonlocal clipped
        if not b:
            return b
        x, y, w, h = map_box(b, src, dst)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if (x0, y0, x1, y1) != (x, y, x + w, y + h):
            clipped += 1
        if x1 <= x0 or y1 <= y0:
            return None
        return [x0, y0, x1 - x0, y1 - y0]

    for g in page.get("glyphs", []):
        g["box"] = mb(g.get("box"))
    for m in page.get("marks", []):
        if m.get("box"):
            m["box"] = mb(m["box"])
    for reg in page.get("regions", []):
        reg["box"] = mb(reg.get("box"))
        reg["rules"] = [[[min(W, max(0, q[0])), min(H, max(0, q[1]))]
                         for q in (map_box([pt[0], pt[1], 1, 1], src, dst)[:2] for pt in line)]
                        for line in reg.get("rules", [])]
        for col in reg.get("columns", []):
            col["box"] = mb(col.get("box"))
    return clipped


# ───────────────────────── 稳定 ID ─────────────────────────

def mint_id(prefix: str, *parts: str) -> str:
    """不透明、可复现的 ID：同样输入恒得同一 ID；字面上不含列号格号，免得被当成位置用。"""
    h = hashlib.sha1("|".join(parts).encode("utf-8")).digest()
    return prefix + base64.b32encode(h).decode("ascii").lower()[:10]


def carry_ids(old: dict, new: dict) -> dict:
    """重切之后把旧页的字框 ID 搬到新页上同一块像素的框（规范 §6）。

    规则与 CV `feedback/bindings.py` 同源：同一张图（`image.sha256` 相同）上，
    IoU ≥ 0.85 视为同一框，0.6~0.85 且两边都只有这一个对象也算；
    其余（切开、合并、只部分重合）给新 ID，`prev` 记下压到的旧 ID 供人裁搬家。
    图不同时：v0.1 同一 canvas 且两边 `image.region` 都已知（重裁）→ 坐标已在同一 canvas 上，照常承接；
    否则（重扫、裁剪区不明）不承接，全部新 ID。
    返回 `{"kept": n, "new": n, "dropped": [旧 ID…]}`，`new` 原地修改。
    """
    stats = {"kept": 0, "new": 0, "dropped": []}
    same_img = old.get("image", {}).get("sha256") == new.get("image", {}).get("sha256")
    # v0.1：坐标都在 canvas 上。同一 canvas、两边的图都记了在原叶上的裁剪区（重裁、裁剪区已知）
    # → 几何已可比，照样按 IoU 承接（待定 #9 定稿）；重扫（canvas 变或裁剪区不明）仍不承接
    oc, nc = old.get("canvas") or {}, new.get("canvas") or {}
    same_canvas = (old.get("schema") in CANVAS_SCHEMAS and new.get("schema") in CANVAS_SCHEMAS and oc.get("id") and oc.get("id") == nc.get("id")
                   and old.get("image", {}).get("region") is not None and new.get("image", {}).get("region") is not None)
    if not (same_img or same_canvas):
        stats["new"] = len(new.get("glyphs", []))
        stats["dropped"] = [g["id"] for g in old.get("glyphs", [])]
        return stats
    olds = [g for g in old.get("glyphs", []) if g.get("box")]
    taken: set[str] = set()
    for g in new.get("glyphs", []):
        if not g.get("box"):
            stats["new"] += 1
            continue
        scored = sorted(((iou(g["box"], o["box"]), o) for o in olds), key=lambda t: -t[0])
        hits = [(s, o) for s, o in scored if s > 0.15]
        best = hits[0] if hits else None
        one_to_one = len(hits) == 1 or (len(hits) > 1 and hits[1][0] <= 0.15)
        if best and best[1]["id"] not in taken and (
                best[0] >= IOU_SAME or (best[0] >= IOU_OK and one_to_one)):
            g["id"] = best[1]["id"]
            g.pop("prev", None)
            taken.add(g["id"])
            stats["kept"] += 1
        else:
            if hits:
                g["prev"] = [o["id"] for _, o in hits]
            stats["new"] += 1
    stats["dropped"] = [o["id"] for o in olds if o["id"] not in taken]
    return stats


# ───────────────────────── 检查 ─────────────────────────

def iter_columns(page: dict):
    for reg in page.get("regions", []):
        for col in reg.get("columns", []):
            yield reg, col


def check(page: dict) -> list[str]:
    """JSON Schema 管不到的结构约束（规范 §7）。返回问题清单，空 = 通过。"""
    errs: list[str] = []
    ver = page.get("schema")
    if ver not in READABLE:
        errs.append(f"schema 应为 {SCHEMA_ID!r}（或旧版 {SCHEMA_V01!r}、{SCHEMA_V0!r}），实为 {ver!r}")
    text = page.get("text", [])
    n = len(text)
    fr = coord_frame(page)
    W, H = fr["width"], fr["height"]
    if ver == SCHEMA_V01:
        errs += _check_v01(page, n)
    elif ver == SCHEMA_ID:
        errs += _check_v02(page, n)

    ids: set[str] = set()

    def _id(x, where):
        i = x.get("id")
        if i in ids:
            errs.append(f"{where}: id 重复 {i}")
        ids.add(i)

    # runs 必须按顺序首尾相接铺满 [0, n)
    pos = 0
    col_ids: dict[str, dict] = {}
    lane_at: list[str | None] = [None] * n
    col_at: list[str | None] = [None] * n
    for reg, col in iter_columns(page):
        _id(col, "column")
        col_ids[col["id"]] = col
        for r in col.get("runs", []):
            s, e = r["text"]
            if s != pos or e < s:
                errs.append(f"列 {col['id']} 的 run {r['text']} 不接续（应从 {pos} 起）")
            for k in range(max(s, 0), min(e, n)):
                lane_at[k] = r["lane"]
                col_at[k] = col["id"]
            pos = max(pos, e)
    for reg in page.get("regions", []):
        _id(reg, "region")
    if pos != n:
        errs.append(f"runs 只铺到 {pos}，text 长 {n}")

    for g in page.get("glyphs", []):
        _id(g, "glyph")
        s, e = g["text"]
        if not (0 <= s <= e <= n):
            errs.append(f"字框 {g['id']} 区间 {g['text']} 越界（text 长 {n}）")
            continue
        if g.get("col") and g["col"] not in col_ids:
            errs.append(f"字框 {g['id']} 指向不存在的列 {g['col']}")
        if e > s:
            if g.get("col") and any(col_at[k] != g["col"] for k in range(s, e)):
                errs.append(f"字框 {g['id']} 的字不全在列 {g['col']} 的 runs 里")
            if g.get("lane") and any(lane_at[k] != g["lane"] for k in range(s, e)):
                errs.append(f"字框 {g['id']} lane={g['lane']} 与 runs 不符")
        b = g.get("box")
        if b and (b[0] < 0 or b[1] < 0 or b[0] + b[2] > W or b[1] + b[3] > H):
            errs.append(f"字框 {g['id']} 出图 {b}（图 {W}×{H}）")
    for m in page.get("marks", []):
        _id(m, "mark")
    for nm in page.get("norm", []):
        if not (0 <= nm["i"] < n):
            errs.append(f"norm 下标 {nm['i']} 越界")
    return errs


def _check_canvas(page: dict) -> list[str]:
    errs: list[str] = []
    c = page.get("canvas")
    if not c:
        return [f"{page.get('schema')} 必须有 canvas 块"]
    seq = c.get("seq")
    if seq is not None and not (len(seq) in (4, 5) and seq[:4].isdigit() and (len(seq) == 4 or seq[4].isalpha())):
        errs.append(f"canvas.seq 应为 4 位页序 + 可选后缀 a–z，实为 {seq!r}")
    if c.get("id") and seq and not c["id"].endswith(f"/canvas/{int(page['volume']['index']):02d}/{seq}"):
        errs.append(f"canvas.id 与册号/页序对不上：{c['id']}")
    sel = selector_xywh(c)
    if sel is not None and (sel[2], sel[3]) != (c["width"], c["height"]):
        errs.append(f"拆块 canvas 尺寸 {c['width']}×{c['height']} 应等于裁剪框 {sel[2]}×{sel[3]}")
    return errs


def _check_norm_why(page: dict) -> list[str]:
    errs: list[str] = []
    for nm in page.get("norm", []):
        if nm.get("why") not in NORM_WHY:
            errs.append(f"norm[{nm['i']}].why 只允许 {NORM_WHY}（校勘改字不进 norm），实为 {nm.get('why')!r}")
    return errs


def _check_v01(page: dict, n: int) -> list[str]:
    errs = _check_canvas(page) + _check_norm_why(page)
    seen = set()
    for z in page.get("zi", []):
        i = z.get("i")
        if not isinstance(i, int) or not (0 <= i < n):
            errs.append(f"zi 下标 {i} 越界")
            continue
        if i in seen:
            errs.append(f"zi 下标 {i} 重复")
        seen.add(i)
        if z.get("form") not in ZI_FORMS:
            errs.append(f"zi[{i}].form 只允许 {ZI_FORMS}")
        if page["text"][i] == "":
            errs.append(f"zi[{i}] 指向阙文位（阙文不是组字）")
    return errs


def _check_v02(page: dict, n: int) -> list[str]:
    """v0.2 的文本口径：阙文 = 「□」+ `lacuna` 标记；组字两层；候选字与放行通道。"""
    errs = _check_canvas(page) + _check_norm_why(page)
    text = page.get("text", [])
    for i, t in enumerate(text):
        if t == "":
            errs.append(f"text[{i}] 是空串：v0.2 的阙文写「{LACUNA_CHAR}」并记进 lacuna")
    lac = page.get("lacuna", [])
    if list(lac) != sorted(set(lac)):
        errs.append("lacuna 应升序、不重复")
    for i in lac:
        if not isinstance(i, int) or not (0 <= i < n):
            errs.append(f"lacuna 下标 {i} 越界")
        elif text[i] != LACUNA_CHAR:
            errs.append(f"lacuna[{i}] 指向 {text[i]!r}：阙文位的 text 必须是「{LACUNA_CHAR}」")
    lac_set = set(lac)
    for g in page.get("glyphs", []):
        s, e = g["text"]
        if g.get("lacuna") == "unreadable" and e - s == 1 and s not in lac_set:
            errs.append(f"字框 {g['id']} 标了 unreadable，但 text[{s}] 不在页上 lacuna 里")
        cand = g.get("cand") or {}
        bad = [k for k in cand if k not in CAND_KEYS]
        if bad:
            errs.append(f"字框 {g['id']} 的 cand 只认 {CAND_KEYS}，多了 {bad}")
    seen = set()
    for z in page.get("zi", []):
        i = z.get("i")
        if not isinstance(i, int) or not (0 <= i < n):
            errs.append(f"zi 下标 {i} 越界")
            continue
        if i in seen:
            errs.append(f"zi 下标 {i} 重复")
        seen.add(i)
        if ("ids" in z) == ("desc" in z) or not (z.get("ids") or z.get("desc")):
            errs.append(f"zi[{i}] 要有且只有 ids、desc 之一，且非空")
        if i in lac_set:
            errs.append(f"zi[{i}] 指向阙文位（阙文不是组字）")
        rel = z.get("rel")
        if text[i] == ZI_NO_NEAR:
            if rel is not None:
                errs.append(f"zi[{i}] 还没有近似字（text 是「{ZI_NO_NEAR}」），rel 应为空")
        elif rel not in ZI_REL:
            errs.append(f"zi[{i}].rel 只允许 {ZI_REL}，实为 {rel!r}")
        if len(text[i]) > 2 or any(0x2FF0 <= ord(ch) <= 0x2FFF for ch in text[i]):
            errs.append(f"zi[{i}]：text 里应是近似的已收字，不是 IDS/描述 {text[i]!r}（原形写进 ids/desc）")
    return errs


def lacuna_set(page: dict) -> set[int]:
    """阙文位下标：v0.2 读页上 `lacuna`；v0/v0.1 读 `text` 里的空串。"""
    if page.get("schema") == SCHEMA_ID:
        return set(page.get("lacuna", []))
    return {i for i, t in enumerate(page.get("text", [])) if t == ""}


def zi_at(page: dict) -> dict[int, str]:
    """组字位 → 原形（IDS 或描述文字，导出 `:zi[…]` 用）。v0.2 在 `zi[].ids/desc`；v0/v0.1 就是 `text[i]`。"""
    if page.get("schema") == SCHEMA_ID:
        return {z["i"]: z.get("ids") or z.get("desc") for z in page.get("zi", [])}
    return {z["i"]: page["text"][z["i"]] for z in page.get("zi", [])}


def validate_schema(page: dict) -> list[str]:
    """按 JSON Schema 校验；没装 jsonschema 时返回 ["jsonschema 未安装"]（不算失败由调用方定）。"""
    try:
        import jsonschema
    except ImportError:          # pragma: no cover
        return ["jsonschema 未安装"]
    path = SCHEMA_PATHS.get(page.get("schema"), SCHEMA_PATH)
    schema = json.loads(path.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(page)]


def unboxed_tokens(page: dict) -> list[int]:
    """没有任何字框引用的字元下标（yolo 的「待框」溢出字、整理本补进来的字……）。"""
    cov = [False] * len(page.get("text", []))
    for g in page.get("glyphs", []):
        for k in range(*g["text"]):
            cov[k] = True
    return [i for i, c in enumerate(cov) if not c]


# ───────────────────────── 导出：guji-markdown ─────────────────────────

def _token_md(page: dict, i: int, guess_at: dict[int, str], lac: set[int]) -> str:
    t = page["text"][i]
    if i in lac:
        return "[[]]"
    if t == "□" and i in guess_at:
        return f"□{{guess={guess_at[i]}}}"
    return t


def to_guji_markdown(page: dict, *, page_comment: bool = True, keep_empty_cols: bool = False,
                     layer: str = "orig") -> str:
    """一列一行的 guji-markdown（与 CV `render/guji_markdown.render_page` 逐字相同的记法）。

    抬头 `^`×级数、行首留白 `.`×格数、双行夹注 `<右|左>`、单行小注 `:jz[…]{type=单行}`、
    阙文 `[[]]`（**每个阙文位一个，不合并**，guji-markdown §13；v0.2 = `lacuna` 标的位，旧版 = 空串）、
    残字 `□{guess=X}`、组字 `:zi[…]`（§16，v0.2 取 `zi[].ids/desc`，text 里的近似字不进 md）。
    不带阙文标记的「□」是真字，照出「□」。`layer="norm"` 时字元换成规范层（`norm` 有条目的位）。
    """
    guess_at: dict[int, str] = {}
    for g in page.get("glyphs", []):
        if g.get("guess") and g["text"][1] - g["text"][0] == 1:
            guess_at[g["text"][0]] = g["guess"]
    norm = {nm["i"]: nm["t"] for nm in page.get("norm", [])} if layer == "norm" else {}
    zi = zi_at(page)
    lac = lacuna_set(page)

    def tok(i):
        if i in norm:
            return norm[i]
        if i in zi:                     # guji-markdown §16 组字：IDS 或描述文字原样放进 :zi[…]
            return f":zi[{zi[i]}]"
        return _token_md(page, i, guess_at, lac)

    lines: list[str] = []
    if page_comment:
        lines.append(f"<!-- p{page['page']['index']} -->")
    for _, col in iter_columns(page):
        runs = col.get("runs", [])
        if not any(r["text"][1] > r["text"][0] for r in runs):
            if keep_empty_cols:
                lines.append("")
            continue
        out = [("^" * int(col.get("raised", 0) or 0)) + ("." * int(col.get("lead_blank", 0) or 0))]
        k = 0
        while k < len(runs):
            r = runs[k]
            seg = "".join(tok(i) for i in range(*r["text"]))
            if r["lane"] in ("jz_r", "jz_l"):
                right = seg if r["lane"] == "jz_r" else ""
                left = seg if r["lane"] == "jz_l" else ""
                if r["lane"] == "jz_r" and k + 1 < len(runs) and runs[k + 1]["lane"] == "jz_l":
                    left = "".join(tok(i) for i in range(*runs[k + 1]["text"]))
                    k += 1
                if right and left:
                    out.append(f"<{right}|{left}>")
                elif right or left:
                    out.append(f"<{right}{left}>")
            elif r["lane"] == "solo":
                if seg:
                    out.append(":jz[" + seg.replace("[[]]", "□") + "]{type=单行}")
            else:
                out.append(seg)
            k += 1
        lines.append("".join(out))
    return "\n".join(lines)


# ───────────────────────── 导出：IIIF / W3C Web Annotation ─────────────────────────

def to_iiif_annotations(page: dict, canvas_id: str | None = None, *, canvas_image: dict | None = None,
                        page_id_base: str | None = None, layer: str = "orig") -> dict:
    """一页字框 → IIIF Presentation 3 `AnnotationPage`（W3C Web Annotation）。

    v0.1：坐标已经在 canvas 上，`canvas_id` 缺省取 `page.canvas.id`，target 直接是
    `<canvas id>#xywh=x,y,w,h`（网站总管约定）。v0 文件照旧：坐标在 `image` 上，
    `canvas_image` 给出 Canvas 那张图时按 `map_box` 换算。
    每框一条 `supplementing` 注释，body 是框里的字（规范层可选），审核状态在 `kyg:review`。
    """
    canvas_id = canvas_id or (page.get("canvas") or {}).get("id")
    if not canvas_id:
        raise ValueError("没有 canvas id：v0.1 页请填 canvas.id，v0 页请传 canvas_id")
    src = coord_frame(page)
    dst = canvas_image or src
    base = page_id_base or f"{canvas_id}/annotations/guji-page"
    norm = {nm["i"]: nm["t"] for nm in page.get("norm", [])} if layer == "norm" else {}
    lac = lacuna_set(page)
    items = []
    for g in page.get("glyphs", []):
        if not g.get("box"):
            continue
        s, e = g["text"]
        value = "".join(norm.get(i, page["text"][i]) for i in range(s, e))
        x, y, w, h = map_box(g["box"], src, dst)
        ann = {
            "id": f"{base}/{g['id']}",
            "type": "Annotation",
            "motivation": "supplementing",
            "body": {"type": "TextualBody", "value": value or "", "format": "text/plain",
                     "language": "zh-Hant"},
            "target": f"{canvas_id}#xywh={x},{y},{w},{h}",
        }
        if g.get("review"):
            ann["kyg:review"] = g["review"]
        if any(i in lac for i in range(s, e)):
            ann["kyg:lacuna"] = True          # 框里是阙文（v0.2 body 是「□」，旧版是空串）
        items.append(ann)
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": base,
        "type": "AnnotationPage",
        "items": items,
    }


def to_iiif_canvas(page: dict, *, annotation_page_id: str | None = None) -> dict:
    """本页的 IIIF Canvas 骨架（网站 manifest 用；图片资源由网站按图源另挂）。

    拆块页按网站约定在 canvas 上写 `source`：原叶 id + `FragmentSelector` `xywh=` 裁剪框，
    与本格式 `image.region`（CV 跑批那张图恰是这一块时）一一对应，见规范 §3.3。
    """
    c = page.get("canvas")
    if not c or not c.get("id"):
        raise ValueError("v0.1 页才有 canvas，且要有 canvas.id")
    out = {"id": c["id"], "type": "Canvas", "label": {"none": [c.get("seq") or ""]},
           "width": c["width"], "height": c["height"]}
    if c.get("source"):
        out["source"] = {"id": c["source"].get("id"), "type": "Image",
                         "selector": dict(c["source"]["selector"])}
    out["annotations"] = [{"id": annotation_page_id or f"{c['id']}/annotations/guji-page",
                           "type": "AnnotationPage"}]
    return out


# ───────────────────────── 入库与升级 ─────────────────────────

def strip_ext(page: dict) -> dict:
    """入 book-text 前去掉工具私有的 `ext`（顶层、区、列、字框、标记），返回新对象。

    文本总管 #361·6：去掉后导出的 guji-markdown 必须不变（测试钉住）。
    """
    import copy
    p = copy.deepcopy(page)
    p.pop("ext", None)
    for reg in p.get("regions", []):
        reg.pop("ext", None)
        for col in reg.get("columns", []):
            col.pop("ext", None)
    for g in p.get("glyphs", []):
        g.pop("ext", None)
    for m in p.get("marks", []):
        m.pop("ext", None)
    return p


def upgrade(page: dict, *, canvas: dict | None = None) -> dict:
    """旧版一路升到 v0.2（原地改并返回）：v0 → v0.1 → v0.2。

    v0 → v0.1：v0 的坐标在 `image` 上；不给 `canvas` 时就拿 `image` 当 canvas（id/seq 为 null，
    拆块页按 `image.region` 生成 selector）；给了且帧不同，几何整体搬过去。
    v0.1 → v0.2：见 `_upgrade_v01`。
    """
    if page.get("schema") == SCHEMA_ID:
        return page
    if page.get("schema") == SCHEMA_V01:
        return _upgrade_v01(page)
    if page.get("schema") != SCHEMA_V0:
        raise ValueError(f"不认识的 schema {page.get('schema')!r}")
    img = page["image"]
    if canvas is None:
        src = img.get("source") or {}
        canvas = make_canvas(None, page["volume"]["index"], None, width=img["width"], height=img["height"],
                             source_id=src.get("id"),
                             source_size=(src["width"], src["height"]) if src.get("width") else None,
                             xywh=img.get("region"))
    else:
        dst = canvas_frame(canvas)
        if (dst["width"], dst["height"], dst.get("region")) != (img["width"], img["height"], img.get("region")):
            remap_geometry(page, img, dst)
    page["schema"] = SCHEMA_V01
    page["canvas"] = canvas
    page.setdefault("zi", [])
    return _upgrade_v01(page)


def _upgrade_v01(page: dict) -> dict:
    """v0.1 → v0.2（用户 10-02 裁定）。导出的 guji-markdown 升级前后逐字相同（测试钉住）。

    - 阙文：`text` 里的空串 → 「□」，下标记进页上 `lacuna`；原有的「□」不动（真字）。
    - 组字：v0.1 的 `text[i]` 是 IDS/描述 → 挪进 `zi[].ids/desc`；近似字不知道，`text[i]` 放「〓」、`rel` 留空，
      等人或 5-b 给出近似字后再填。
    - 字框：`channel` 缺时从 `ext.cv.channel` 补（CV 导出的旧页有）；候选字 `cand` 旧页没有，留空。
    """
    text = page["text"]
    page["lacuna"] = [i for i, t in enumerate(text) if t == ""]
    for i in page["lacuna"]:
        text[i] = LACUNA_CHAR
    zi = []
    for z in page.get("zi", []):
        i = z["i"]
        zi.append({"i": i, z.get("form", "ids"): text[i], "rel": None})
        text[i] = ZI_NO_NEAR
    page["zi"] = zi
    for g in page.get("glyphs", []):
        cv = (g.get("ext") or {}).get("cv") or {}
        if "channel" not in g and "channel" in cv:
            g["channel"] = cv["channel"]
    page["schema"] = SCHEMA_ID
    return page


def read_page(path: str | Path) -> dict:
    """读一页，旧版自动升到 v0.2。"""
    return upgrade(load(path))


# ───────────────────────── 册级索引（v0.1 预留） ─────────────────────────

def volume_index(pages: list[dict], *, files: dict | None = None, book_text_version: str | None = None) -> dict:
    """`layout/index.json`：一册的页表。

    文本总管 #361·5：字段等第一批入库再定，**先定一项**——每页属于 book-text 哪个版本的哪一章
    （`chapters: [{"version", "chapter": "NNN", "text": [s, e] | null}]`，`text` 是本页文本流里
    属于该章的区间，null = 整页）。现在由 CV 导出时留空，文本一侧入库对齐时填。
    """
    pages = sorted(pages, key=lambda p: p["page"]["index"])
    first = pages[0] if pages else {}
    rows = []
    for p in pages:
        key = p["page"]["index"]
        f = (files or {}).get(key)
        rows.append({
            "page": key,
            "canvas_seq": (p.get("canvas") or {}).get("seq"),
            "canvas_id": (p.get("canvas") or {}).get("id"),
            "file": f["file"] if f else f"p{key:04d}.guji-page.json",
            "sha256": f.get("sha256") if f else None,
            "image_sha256": p["image"].get("sha256"),
            "chapters": [],
        })
    return {"schema": INDEX_SCHEMA_ID,
            "book": first.get("book"), "volume": first.get("volume"),
            "page_schema": SCHEMA_ID,
            "book_text": {"version": book_text_version},
            "pages": rows}


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(page: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


__all__ = [
    "SCHEMA_ID", "SCHEMA_V01", "SCHEMA_V0", "LACUNA_CHAR", "ZI_REL", "ZI_NO_NEAR", "CAND_KEYS",
    "lacuna_set", "zi_at", "LANES", "REVIEW", "tr_bbox_to_xywh", "tr_point_to_tl", "union_xywh", "iou",
    "map_box", "scaled_image", "canvas_id", "ia_image_id", "seq_for_ws_page", "make_canvas",
    "canvas_frame", "coord_frame", "remap_geometry", "mint_id", "carry_ids", "check", "validate_schema",
    "unboxed_tokens", "to_guji_markdown", "to_iiif_annotations", "to_iiif_canvas", "strip_ext",
    "upgrade", "read_page", "volume_index", "load", "dump",
]

