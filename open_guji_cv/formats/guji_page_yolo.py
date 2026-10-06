# -*- coding: utf-8 -*-
"""yolo_tool `<名>_project.json` ↔ guji-page v0.2（每字带坐标的页面文本）。

yolo_tool（open-guji/yolo_tool，本地校对工作台）**不改**：它的工程文件格式已经并进
guji-page 的设计（规范 doc/formats/guji_page_v0.md §九），互转放在本仓。本模块只用标准库，
不 import 本仓其它模块，也不 import PyQt / ultralytics，整个文件拷走也能单独跑：

    python -m open_guji_cv.formats.guji_page_yolo to-guji 书_project.json OUT_DIR --book-id 96mid1ogzk \
            --volume 3 [--size 2361x3096] [--source-size 2361x3096] [--zoom 2]
    python -m open_guji_cv.formats.guji_page_yolo to-yolo OUT_DIR/*.guji-page.json 新_project.json

## project.json 结构（从 yolo_tool ui/main_window.py、ui/components.py 摸出来的实况，2026-10-02 `15c5f88`）

顶层 `{"<页下标，0 起>": 页}`。页：

| 键 | 含义 |
|---|---|
| `type` | 版面框（列条）数组 |
| `slide` | 单字框数组 |
| `sort_mode` | `{"type": "auto"|"manual", "slide": …}`，手动序锁定（可缺） |
| `source_text` | 整页权威文本，**字元数组**（可缺；缺时文本 = 各框 `ocr_text` 按读序拼） |

每框是位置数组，**靠长度区分版本**（`BoundingBox.from_dict`）：

| 下标 | 字段 | 说明 |
|---|---|---|
| 0–3 | x, y, w, h | 渲染图像素（PDF 按 `fitz.Matrix(2,2)` 渲染＝PDF 点×2；图片＝原像素），左上原点，浮点 |
| 4 | cls_name | type：text/subText/midText/subText2/midSubText（ear 在推理时被并成 text）；slide 恒 text |
| 5 | conf | YOLO 检测置信度；手画框 1.0 |
| 6 | box_type | type / slide |
| 7 | id_num | type：列序；slide：**全页**读序号（1 起） |
| 8 | ocr_text | 框里的字（≥10 位才有） |
| 9 | ocr_conf | 识别置信度；**2.0 是哨兵＝人工填/改过**（≥10 位） |
| 10 | local_id | type：同 id_num；slide：**本列内**序号（不是栏号）（≥11 位） |
| 11 | rec_text | 「OCR 校验比对」缓存（12 位才有） |

长度 8（推理刚出、未识别）、10、11、12 都在用；10 位是 `flow_update_text` 给旧框补位补出来的。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sys
from pathlib import Path

SCHEMA_ID = "guji-page/0.2"
LACUNA_CHAR = "□"          # v0.2：阙文位在 text 里放「□」、下标记进 lacuna（yolo 里是空串）
LANE_OF_CLS = {"text": "main", "subText": "jz_r", "subText2": "jz_l",
               "midText": "main", "midSubText": "jz_r"}
REGION_OF_CLS = {"midText": "banxin", "midSubText": "banxin"}
CLS_OF_LANE = {"main": "text", "jz_r": "subText", "jz_l": "subText2", "solo": "subText"}
HUMAN_SENTINEL = 2.0


# ───────────── 小工具 ─────────────

def _mint(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).digest()
    return prefix + base64.b32encode(h).decode("ascii").lower()[:10]


def _xywh_int(x, y, w, h) -> list[int]:
    xi, yi = math.floor(x), math.floor(y)
    return [xi, yi, max(1, math.ceil(x + w) - xi), max(1, math.ceil(y + h) - yi)]


def _inter_area(a, b) -> float:
    iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return iw * ih if iw > 0 and ih > 0 else 0.0


def _union(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _field(b, i, default):
    return b[i] if len(b) > i else default


def reading_order(p: dict):
    """复刻 `MainWindow._page_slide_order_arrays`：列按 type id 排，单字框按交集面积
    最大归列，列内手动序看 id、自动序看中心 y。返回 `[(列下标, [slide 下标…]), …]` 与孤框。"""
    t_list = p.get("type", [])
    s_list = p.get("slide", [])
    t_idx = sorted(range(len(t_list)),
                   key=lambda i: t_list[i][7] if len(t_list[i]) > 7 and t_list[i][7] > 0 else 9 ** 9)
    lines = {i: [] for i in t_idx}
    orphans = []
    for si, s in enumerate(s_list):
        best, area = None, 0.0
        for ti in t_idx:
            a = _inter_area(s[:4], t_list[ti][:4])
            if a > area:
                best, area = ti, a
        (lines[best] if best is not None else orphans).append(si)
    manual = (p.get("sort_mode") or {}).get("slide") == "manual"
    for ti in t_idx:
        if manual:
            lines[ti].sort(key=lambda si: s_list[si][7] if len(s_list[si]) > 7 and s_list[si][7] > 0
                           else s_list[si][1] + s_list[si][3] / 2.0)
        else:
            lines[ti].sort(key=lambda si: s_list[si][1] + s_list[si][3] / 2.0)
    return [(ti, lines[ti]) for ti in t_idx], orphans


# ───────────── yolo → guji ─────────────

def page_to_guji(key: str, p: dict, *, book_id: str, volume: int, size=None, source_size=None,
                 render: dict | None = None, pdf_sha256: str | None = None) -> dict:
    t_list, s_list = p.get("type", []), p.get("slide", [])
    order, orphans = reading_order(p)
    flat = [si for _, sis in order for si in sis]
    src = p.get("source_text")
    if src:
        tokens = list(src)
    else:
        tokens = [s_list[si][8] for si in flat if len(s_list[si]) > 8 and s_list[si][8]]

    page_index = int(key) + 1
    page_id = f"{book_id}/{volume}/{page_index}"
    regions: dict[str, dict] = {}
    glyphs, marks = [], []
    pos = 0             # 文本流游标
    k_tok = 0           # 有 source_text 时：第 k 个框对第 k 个字
    last_col = None
    for ti, sis in order:
        t = t_list[ti]
        cls = t[4]
        rk = REGION_OF_CLS.get(cls, "body")
        reg = regions.setdefault(rk, {"id": f"r_{rk}", "kind": rk, "box": None, "columns": []})
        lane = LANE_OF_CLS.get(cls, "main")
        col = {"id": f"c{_field(t, 7, ti + 1)}_{ti}", "n": int(_field(t, 7, ti + 1)), "kind": "body",
               "box": _xywh_int(*t[:4]), "runs": [], "ext": {"yolo": {"raw": t, "index": ti}}}
        start = pos
        for si in sis:
            s = s_list[si]
            if src:
                has = k_tok < len(tokens)
                rng = [pos, pos + 1] if has else [pos, pos]
                k_tok += has
            else:
                txt = _field(s, 8, "")
                rng = [pos, pos + 1] if txt else [pos, pos]
            pos = rng[1]
            glyphs.append(_glyph(page_id, s, si, rng, col["id"], lane))
        if pos > start:
            col["runs"].append({"lane": lane, "text": [start, pos]})
        reg["columns"].append(col)
        last_col = (col, lane)
    # 溢出的字（source_text 比框多）：yolo 叫「待框」，挂在最后一列末尾
    if pos < len(tokens):
        if last_col is None:
            reg = regions.setdefault("body", {"id": "r_body", "kind": "body", "box": None, "columns": []})
            col = {"id": "c_overflow", "kind": "body", "box": None, "runs": []}
            reg["columns"].append(col)
            last_col = (col, "main")
        col, lane = last_col
        if col["runs"] and col["runs"][-1]["text"][1] == pos and col["runs"][-1]["lane"] == lane:
            col["runs"][-1]["text"][1] = len(tokens)
        else:
            col["runs"].append({"lane": lane, "text": [pos, len(tokens)]})
        pos = len(tokens)
    for si in orphans:
        g = _glyph(page_id, s_list[si], si, [pos, pos], None, None)
        g.setdefault("flags", []).append("orphan")
        glyphs.append(g)
    for g in glyphs:        # 记下转换时框里的字，回写时只有它变了才算「格式里改过字」
        s0, e0 = g["text"]
        g["ext"]["yolo"]["t0"] = "".join(tokens[s0:e0])
    # v0.2：yolo 的空串字元（source_text 里的缺字）= 阙文 → 「□」+ lacuna；回写时还原成空串
    lacuna = [i for i, t in enumerate(tokens) if t == ""]
    tokens = [LACUNA_CHAR if t == "" else t for t in tokens]
    for reg in regions.values():
        boxes = [c["box"] for c in reg["columns"] if c.get("box")]
        reg["box"] = _union(boxes) if boxes else None

    all_boxes = [b[:4] for b in t_list + s_list]
    if size:
        W, H = size
    elif all_boxes:
        W = math.ceil(max(b[0] + b[2] for b in all_boxes))
        H = math.ceil(max(b[1] + b[3] for b in all_boxes))
    else:
        W = H = 1
    image = {"width": int(W), "height": int(H), "sha256": None}
    if render:
        image["render"] = dict(render)
    if pdf_sha256:
        image.setdefault("render", {})["pdf_sha256"] = pdf_sha256
    if source_size:
        image["source"] = {"kind": "scan", "width": int(source_size[0]), "height": int(source_size[1])}
    if not size:
        image["note"] = "宽高未给，取框的外接范围代替（只够自洽，不够叠回原图）"

    return {
        "schema": SCHEMA_ID,
        "page_id": page_id,
        "book": {"id": book_id},
        "volume": {"index": int(volume)},
        "page": {"index": page_index},
        "image": image,
        # yolo 的坐标在 PDF 渲染图上，没有 IIIF canvas：id/seq 留 null，canvas 帧 = 渲染图
        "canvas": {"id": None, "seq": None, "width": image["width"], "height": image["height"]},
        "zi": [],
        "producers": {"yolo": {"tool": "yolo_tool"}},
        "text": tokens,
        "lacuna": lacuna,
        "norm": [],
        "regions": list(regions.values()),
        "glyphs": glyphs,
        "marks": marks,
        "ext": {"yolo": {"key": key,
                         "keys": [k for k in p.keys()],
                         "sort_mode": p.get("sort_mode"),
                         "source_text": "source_text" in p}},
    }


def _glyph(page_id, s, si, rng, col_id, lane):
    ocr_text, ocr_conf = _field(s, 8, ""), _field(s, 9, 0.0)
    human = ocr_conf == HUMAN_SENTINEL
    g = {"id": _mint("g", page_id, "yolo", str(si), json.dumps(s[:4])),
         "text": rng, "box": _xywh_int(*s[:4]), "col": col_id, "lane": lane,
         "by": {"box": "yolo", "text": "yolo" if rng[1] > rng[0] else None},
         "method": "yolo:human" if human else ("ocr" if ocr_text else "yolo"),
         "review": "human" if human else "pending",
         "conf": None if human or not ocr_text or not isinstance(ocr_conf, (int, float)) else float(ocr_conf),
         "ext": {"yolo": {"raw": s, "index": si}}}
    if col_id is None:
        g.pop("col")
        g.pop("lane")
    return g


def project_to_pages(project: dict, *, book_id: str, volume: int, sizes=None, source_sizes=None,
                     render=None, pdf_sha256=None) -> list[dict]:
    out = []
    for key, p in project.items():
        if not key.lstrip("-").isdigit():
            continue
        i = int(key)
        out.append(page_to_guji(key, p, book_id=book_id, volume=volume,
                                size=(sizes or {}).get(i), source_size=(source_sizes or {}).get(i),
                                render=render, pdf_sha256=pdf_sha256))
    extra = {k: v for k, v in project.items() if not k.lstrip("-").isdigit()}
    if extra and out:
        out[0]["ext"]["yolo"]["project_extra"] = extra
    return out


# ───────────── guji → yolo ─────────────

def page_to_yolo(page: dict) -> tuple[str, dict]:
    """一页 guji-page → (页键, yolo 页)。

    带 `ext.yolo.raw` 的框（从 yolo 来的）**原样回写**，只把格式里真改过的字段盖上去
    （框挪了、字改了），所以 yolo → guji → yolo 逐字节一致；没有 raw 的（CV 出的页）新建：
    每个 run 一条版面框（夹注右/左分别是 subText/subText2），单字框按读序编号、
    `sort_mode.slide = manual` 锁住顺序（yolo 自动序按中心 y，会把列内正文与夹注排乱）。
    """
    ext = (page.get("ext") or {}).get("yolo") or {}
    key = ext.get("key", str(page["page"]["index"] - 1))
    # yolo 那边的字：v0.2 的阙文位（「□」+ lacuna）回到空串，其余照 text
    lac = set(page.get("lacuna", [])) if page.get("schema") == SCHEMA_ID else set()
    text = ["" if i in lac else t for i, t in enumerate(page["text"])]
    from_yolo = all(((c.get("ext") or {}).get("yolo") or {}).get("raw") is not None
                    for reg in page["regions"] for c in reg["columns"] if c.get("box"))

    type_list: list = []
    slide_list: list = []
    if from_yolo:
        cols = sorted((c for reg in page["regions"] for c in reg["columns"] if c.get("ext")),
                      key=lambda c: c["ext"]["yolo"]["index"])
        type_list = [list(c["ext"]["yolo"]["raw"]) for c in cols]
        for c, raw in zip(cols, type_list):
            if _xywh_int(*raw[:4]) != c["box"]:
                raw[:4] = [float(v) for v in c["box"]]
        gl = sorted(page["glyphs"], key=lambda g: ((g.get("ext") or {}).get("yolo") or {}).get("index", 10 ** 9))
        for g in gl:
            raw = list(((g.get("ext") or {}).get("yolo") or {}).get("raw") or [])
            if not raw:
                raw = _new_slide(g, text)
            else:
                if _xywh_int(*raw[:4]) != g["box"]:
                    raw[:4] = [float(v) for v in g["box"]]
                s, e = g["text"]
                t = "".join(text[s:e])
                if t != g["ext"]["yolo"].get("t0", t):
                    while len(raw) < 10:
                        raw.append("" if len(raw) == 8 else 0.0)
                    raw[8] = t
                    raw[9] = HUMAN_SENTINEL if g.get("review") == "human" else raw[9]
            slide_list.append(raw)
    else:
        gid = 0
        tid = 0
        for reg in page["regions"]:
            for c in reg["columns"]:
                for r in c["runs"]:
                    gs = [g for g in page["glyphs"] if g.get("box") and g["text"][0] >= r["text"][0]
                          and g["text"][1] <= r["text"][1] and g["text"][1] > g["text"][0]]
                    if not gs:
                        continue
                    tid += 1
                    strip = _union([g["box"] for g in gs])
                    type_list.append([float(v) for v in strip] + [CLS_OF_LANE[r["lane"]], 1.0, "type",
                                                                  tid, "", 0.0, tid])
                    for loc, g in enumerate(sorted(gs, key=lambda g: g["text"][0]), start=1):
                        gid += 1
                        raw = _new_slide(g, text)
                        raw[7], raw[10] = gid, loc
                        slide_list.append(raw)
    p: dict = {}
    for k in ext.get("keys") or ["type", "slide", "sort_mode", "source_text"]:
        if k == "type":
            p["type"] = type_list
        elif k == "slide":
            p["slide"] = slide_list
        elif k == "sort_mode":
            p["sort_mode"] = ext.get("sort_mode") or {"type": "manual", "slide": "manual"}
        elif k == "source_text":
            if ext.get("source_text", True):
                p["source_text"] = list(text)
    return key, p


def _new_slide(g, text):
    s, e = g["text"]
    t = "".join(text[s:e])
    human = g.get("review") == "human"
    conf = HUMAN_SENTINEL if human else (g.get("conf") or 0.0)
    return [float(v) for v in g["box"]] + ["text", 1.0, "slide", 0, t, conf, 0, ""]


def pages_to_project(pages: list[dict]) -> dict:
    proj: dict = {}
    for pg in sorted(pages, key=lambda x: x["page"]["index"]):
        k, p = page_to_yolo(pg)
        proj[k] = p
        extra = ((pg.get("ext") or {}).get("yolo") or {}).get("project_extra")
        if extra:
            proj.update(extra)
    return proj


# ───────────── CLI ─────────────

def _wh(s):
    if not s:
        return None
    w, h = s.lower().split("x")
    return int(w), int(h)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="yolo_tool project.json ↔ guji-page v0.2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("to-guji")
    a1.add_argument("project")
    a1.add_argument("out")
    a1.add_argument("--book-id", required=True)
    a1.add_argument("--volume", type=int, default=1)
    a1.add_argument("--size", help="渲染图宽高 WxH（所有页一样时）")
    a1.add_argument("--source-size", help="原扫描图宽高 WxH（用于换算回原图）")
    a1.add_argument("--zoom", type=float, default=None, help="PDF 渲染倍率（yolo_tool 固定 2）")
    a2 = sub.add_parser("to-yolo")
    a2.add_argument("pages", nargs="+")
    a2.add_argument("out")
    a = ap.parse_args(argv)
    if a.cmd == "to-guji":
        proj = json.loads(Path(a.project).read_text(encoding="utf-8"))
        n = len(proj)
        sizes = {i: _wh(a.size) for i in range(n)} if a.size else None
        ssz = {i: _wh(a.source_size) for i in range(n)} if a.source_size else None
        render = {"from": "pdf", "zoom": a.zoom} if a.zoom else None
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for pg in project_to_pages(proj, book_id=a.book_id, volume=a.volume, sizes=sizes,
                                   source_sizes=ssz, render=render):
            (out / f"p{pg['page']['index']:04d}.guji-page.json").write_text(
                json.dumps(pg, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    pages = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.pages]
    Path(a.out).write_text(json.dumps(pages_to_project(pages), ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
