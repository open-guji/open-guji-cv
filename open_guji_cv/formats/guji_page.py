# -*- coding: utf-8 -*-
"""guji-page v0：每字带坐标的页面文本——格式本身的工具（与 CV 产物无关）。

规范正本：`doc/formats/guji_page_v0.md`；JSON Schema：`formats/guji_page_v0.schema.json`。
这里只放**不依赖任何管线产物**的东西：结构检查、坐标框换算、稳定 ID、两个最小导出器
（guji-markdown、IIIF 注释）。CV 产物 → 本格式在 `guji_page_cv.py`；yolo_tool 那边的
互转在 yolo_tool 仓（只依赖标准库，不 import 本模块）。

几条一眼要记住的口径（规范 §2）：

- 坐标：**本页图像**的整数像素，**左上原点**，框记 `[x, y, w, h]`（与 IIIF `#xywh=` 同序）。
  CV 内部的右上原点 `raw_page_px@top-right` 只在导出时换一次（`tr_bbox_to_xywh`），格式里不出现。
- 文本流 `text` 是真源：一个元素 = 一个「字元」（一个字，也可以是 IDS 串、带异体选择符的字），
  空串 `""` = 阙文。字框 `glyphs[].text = [start, end)` 引用这条流的区间：一框多字 = 区间长 >1，
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

SCHEMA_ID = "guji-page/0"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "formats" / "guji_page_v0.schema.json"

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
    图不同（重扫、重裁）不承接，全部新 ID——那要先经 `map_box` 换到同一坐标再说。
    返回 `{"kept": n, "new": n, "dropped": [旧 ID…]}`，`new` 原地修改。
    """
    stats = {"kept": 0, "new": 0, "dropped": []}
    if old.get("image", {}).get("sha256") != new.get("image", {}).get("sha256"):
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
    if page.get("schema") != SCHEMA_ID:
        errs.append(f"schema 应为 {SCHEMA_ID!r}，实为 {page.get('schema')!r}")
    text = page.get("text", [])
    n = len(text)
    W, H = page["image"]["width"], page["image"]["height"]

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


def validate_schema(page: dict) -> list[str]:
    """按 JSON Schema 校验；没装 jsonschema 时返回 ["jsonschema 未安装"]（不算失败由调用方定）。"""
    try:
        import jsonschema
    except ImportError:          # pragma: no cover
        return ["jsonschema 未安装"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
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

def _token_md(page: dict, i: int, guess_at: dict[int, str]) -> str:
    t = page["text"][i]
    if t == "":
        return "[[]]"
    if t == "□" and i in guess_at:
        return f"□{{guess={guess_at[i]}}}"
    return t


def to_guji_markdown(page: dict, *, page_comment: bool = True, keep_empty_cols: bool = False,
                     layer: str = "orig") -> str:
    """一列一行的 guji-markdown（与 CV `render/guji_markdown.render_page` 逐字相同的记法）。

    抬头 `^`×级数、行首留白 `.`×格数、双行夹注 `<右|左>`、单行小注 `:jz[…]{type=单行}`、
    阙文 `[[]]`、残字 `□{guess=X}`。`layer="norm"` 时字元换成规范层（`norm` 有条目的位）。
    """
    guess_at: dict[int, str] = {}
    for g in page.get("glyphs", []):
        if g.get("guess") and g["text"][1] - g["text"][0] == 1:
            guess_at[g["text"][0]] = g["guess"]
    norm = {nm["i"]: nm["t"] for nm in page.get("norm", [])} if layer == "norm" else {}

    def tok(i):
        return norm[i] if i in norm else _token_md(page, i, guess_at)

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

def to_iiif_annotations(page: dict, canvas_id: str, *, canvas_image: dict | None = None,
                        page_id_base: str | None = None, layer: str = "orig") -> dict:
    """一页字框 → IIIF Presentation 3 `AnnotationPage`（W3C Web Annotation）。

    `canvas_image`：Canvas 对应的那张图的描述（`width/height/region/source`，同 `image` 块）。
    缺省 = 本页图本身；不同时按 `map_box` 换算（缩放档、另一版裁法）。
    每框一条 `supplementing` 注释，body 是框里的字（规范层可选），target 是 `canvas#xywh=`。
    """
    dst = canvas_image or page["image"]
    base = page_id_base or f"{canvas_id}/annotations/guji-page"
    norm = {nm["i"]: nm["t"] for nm in page.get("norm", [])} if layer == "norm" else {}
    items = []
    for g in page.get("glyphs", []):
        if not g.get("box"):
            continue
        s, e = g["text"]
        value = "".join(norm.get(i, page["text"][i]) for i in range(s, e))
        x, y, w, h = map_box(g["box"], page["image"], dst)
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
        items.append(ann)
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": base,
        "type": "AnnotationPage",
        "items": items,
    }


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(page: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


__all__ = [
    "SCHEMA_ID", "LANES", "REVIEW", "tr_bbox_to_xywh", "tr_point_to_tl", "union_xywh", "iou",
    "map_box", "scaled_image", "mint_id", "carry_ids", "check", "validate_schema",
    "unboxed_tokens", "to_guji_markdown", "to_iiif_annotations", "load", "dump",
]

