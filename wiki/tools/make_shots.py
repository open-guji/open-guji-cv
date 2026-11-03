# -*- coding: utf-8 -*-
"""Wiki 截图出图脚本：按 `shots.yaml` 从真实页面与产物画图，写到 `wiki/images/`。

为什么要脚本而不是手截：Wiki 每升一次 MINOR 要整体重改（见 wiki/Wiki维护.md），
截图也要跟着重截。脚本读的是那一版的产物包，重跑一遍就是新图，配色、裁切、宽度都一致。

用法（在 cv 仓根，装好 cv 与 guji-manager）：

    # 1. 准备数据：每部书一个工作区，取原图与产物包（标 main 的那份）
    guji source pull vol04 -w <殿本工作区>
    guji products pack fetch vol04 -w <殿本工作区>
    # 2. 出图（--ws 书ID=工作区，可多个；--only 只出某几张）
    python wiki/tools/make_shots.py --ws 96mid1ogzk=<殿本工作区> [--only step1-border]
    # 带 yolo 图层的图（Step3「和 YOLO 对比」）还要 yolo-tool 的模型：
    #   git clone --depth 1 https://github.com/open-guji/yolo_tool ../yolo_tool
    #   python wiki/tools/make_shots.py ... --yolo ../yolo_tool/model

出图只读产物，不改工作区；字块、列图缺缓存时会按 cv 的规则现场重建（写进工作区 cache/）。
图里不写中文字（图注写在 Wiki 正文里），只有列号这类 ASCII 标记。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "images"

# 统一配色（BGR）。Wiki 正文的图例照这张表写，改了这里要改 wiki/_图例.md
C = {
    "vline": (40, 40, 220),      # 界行、版框竖线：红
    "hline": (200, 90, 20),      # 上下版框：蓝
    "head": (0, 140, 255),       # 抬头：橙
    "char": (40, 160, 40),       # 字格：绿
    "blank": (170, 170, 170),    # 空格：灰
    "sub_a": (200, 60, 160),     # 夹注右行：紫
    "sub_b": (0, 150, 230),      # 夹注左行：橙黄
    "flag": (40, 40, 220),       # 带 flag 的字框：红
    "seal_stain": (180, 50, 200),  # 大印：品红
    "seal_crisp": (0, 140, 255),   # 小印：橙
    "auto": (40, 160, 40),       # 自动放行：绿
    "human": (200, 120, 30),     # 人裁过：蓝
    "review": (40, 40, 220),     # 落人审：红
    "chord": (210, 180, 0),      # 界行两端连成的直线（对照折线）：青
    "yolo": (200, 90, 20),       # yolo-tool 原生单字框：蓝
}
COL_TINTS = [(255, 220, 180), (180, 230, 255)]  # 列带交替底色（浅蓝 / 浅橙）


# ---------------------------------------------------------------- 工作区与产物

class Book:
    """一册：工作区、册号；读原图、产物、缓存图都经 cv 自己的接口。"""

    def __init__(self, ws: Path, book: str):
        self.ws, self.book = ws, book
        os.environ["GUJI_WORKSPACE"] = str(ws)
        from open_guji_cv.core.book import load_book
        from open_guji_cv.products.cache import ImageCache
        from open_guji_cv.products.store import ProductStore
        self.b = load_book(book)
        self.store = ProductStore()
        self.cache = ImageCache()

    def raw(self, page: int) -> np.ndarray:
        from open_guji_cv.utils.image_io import imread
        from open_guji_cv.utils.preclean import effective_raw_path
        img = imread(str(effective_raw_path(self.b, page)))
        if img is None:
            raise SystemExit(f"{self.book} p{page} 没有原图：先 guji source pull {self.book} -w {self.ws}")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return img

    def prod(self, step: str, page: int) -> dict:
        from open_guji_cv.core.spec import page_key
        d = self.store.read_raw(self.book, step, page_key(page))
        if d is None:
            raise SystemExit(f"{self.book} p{page} 没有 {step} 产物：先 guji products pack fetch {self.book} -w {self.ws}")
        return d

    def materialize(self, kind: str, key: str) -> np.ndarray:
        from open_guji_cv.core.step import RunContext
        from open_guji_cv.utils.image_io import imread
        from open_guji_cv import steps as _s  # noqa: F401  注册各步
        f = self.cache.get(self.book, kind, key)
        if f is None:
            ctx = RunContext(self.b, self.store, self.cache, log=lambda _: None)
            f = ctx.materialize(kind, key)
        img = imread(str(f), cv2.IMREAD_GRAYSCALE)
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def tl(x: float, W: int) -> int:
    """规范坐标（右上原点）x → 图像坐标（左上原点）x。"""
    from open_guji_cv.core.anchor import x_tr_to_tl
    return int(round(x_tr_to_tl(x, W)))


def line_x(v: dict, y: float) -> float:
    """折线界行在 y 处的 x（规范坐标），同 render.overlay.draw_vline 的分段法。"""
    if v.get("k2") is None or y <= v["y1"]:
        return v["x_at_top"] + v["slope"] * y
    if y <= v["y2"]:
        return v["x_at_top"] + v["slope"] * v["y1"] + v["k2"] * (y - v["y1"])
    return (v["x_at_top"] + v["slope"] * v["y1"] + v["k2"] * (v["y2"] - v["y1"])
            + v["k3"] * (y - v["y2"]))


def blend(img, mask_img, alpha=0.35):
    return cv2.addWeighted(mask_img, alpha, img, 1 - alpha, 0)


# ---------------------------------------------------------------- 图层

def layer_border(bk, page, img, th):
    from open_guji_cv.render.overlay import draw_vline
    H, W = img.shape[:2]
    bd = bk.prod("border_detect", page)["borders"]
    for v in bd["verticals"]:
        draw_vline(img, v, W, H, C["vline"], th)
    for h in (bd["top"], bd["bottom"]):
        p0 = (W - 1, int(round(h["y_at_right"])))
        p1 = (0, int(round(h["y_at_right"] + h["slope"] * (W - 1))))
        cv2.line(img, p0, p1, C["hline"], th + 1)
    for hr in bd.get("head_raise", []):
        y = int(hr["inner_y"])
        cv2.line(img, (0, y), (W - 1, y), C["head"], th)


def layer_chord(bk, page, img, th):
    """每条界行只取上下两端连一条直线：和折线对照，看中段弯了多少。"""
    H, W = img.shape[:2]
    bd = bk.prod("border_detect", page)["borders"]
    ys = (bd["top"]["y_at_right"], bd["bottom"]["y_at_right"])
    for v in bd["verticals"]:
        p0, p1 = [(tl(line_x(v, y), W), int(round(y))) for y in ys]
        cv2.line(img, p0, p1, C["chord"], max(1, th - 1), cv2.LINE_AA)


YOLO_MODEL: str | None = None
_YOLO = {}


def yolo_chars(bk, page):
    """yolo-tool 原生两段模型（版面 → 单字）在原图上的单字框，左上原点；要 --yolo 给模型目录。"""
    key = (str(bk.ws), bk.book, page)
    if key not in _YOLO:
        if not YOLO_MODEL:
            raise SystemExit("yolo 图层要 --yolo <yolo_tool 的 model/ 目录>")
        from open_guji_cv.books.siku_zongmu.yolo_tool_infer import YoloTool
        if "tool" not in _YOLO:
            _YOLO["tool"] = YoloTool(YOLO_MODEL)
        _, chars = _YOLO["tool"].infer(bk.raw(page))
        _YOLO[key] = [b for b in chars if b.cls != "ear"]
    return _YOLO[key]


def layer_yolo(bk, page, img, th):
    for b in yolo_chars(bk, page):
        cv2.rectangle(img, (int(b.x0), int(b.y0)), (int(b.x1), int(b.y1)), C["yolo"], th)


def layer_columns(bk, page, img, th):
    H, W = img.shape[:2]
    cols = bk.prod("column_warp", page)["column_windows"]["columns"]
    tint = img.copy()
    for i, c in enumerate(cols):
        ys = np.linspace(c["top_y"], c["bottom_y"], 40)
        right = [(tl(line_x(c["right_line"], y), W), int(y)) for y in ys]
        left = [(tl(line_x(c["left_line"], y), W), int(y)) for y in ys[::-1]]
        cv2.fillPoly(tint, [np.array(right + left, np.int32)], COL_TINTS[i % 2])
    img[:] = blend(img, tint, 0.45)
    for c in cols:
        xr = tl(c["right_line"]["x_at_top"], W)
        xl = tl(c["left_line"]["x_at_top"], W)
        cv2.putText(img, str(c["col"]), ((xr + xl) // 2 - 12, max(40, int(c["top_y"]) - 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)


def _quad(q, W):
    return np.array([(tl(x, W), int(round(y))) for x, y in q], np.int32)


def layer_cells(bk, page, img, th):
    H, W = img.shape[:2]
    for col in bk.prod("row_segment", page)["cells"]["columns"]:
        for c in col["cells"]:
            q = c.get("quad_page")
            if not q:
                continue
            if c.get("sub") in ("a", "b"):
                color = C["sub_" + c["sub"]]
            else:
                color = C["char"] if c["kind"] == "char" else C["blank"]
            cv2.polylines(img, [_quad(q, W)], True, color, th)


def _chars(bk, page):
    for col in bk.prod("cell_shrink", page)["char_index"]["columns"]:
        for c in col["chars"]:
            if c.get("bbox_page"):
                yield c


def _rect(c, W):
    x0, y0, x1, y1 = c["bbox_page"]
    return (tl(x1, W), int(y0)), (tl(x0, W), int(y1))


def layer_shrink(bk, page, img, th):
    W = img.shape[1]
    for c in _chars(bk, page):
        p0, p1 = _rect(c, W)
        cv2.rectangle(img, p0, p1, C["flag"] if c["flags"] else C["char"], th)


def layer_tight(bk, page, img, th):
    """Step4 紧框，一律绿色（和 YOLO 字框对照时用，不按 flag 标红）。"""
    W = img.shape[1]
    for c in _chars(bk, page):
        p0, p1 = _rect(c, W)
        cv2.rectangle(img, p0, p1, C["char"], th)


def layer_seal(bk, page, img, th):
    W = img.shape[1]
    for s in bk.prod("seal_detect", page)["seals"]["seals"]:
        x0, y0, x1, y1 = s["bbox"]
        color = C["seal_stain"] if s["kind"] == "stain" else C["seal_crisp"]
        cv2.rectangle(img, (tl(x1, W), int(y0)), (tl(x0, W), int(y1)), color, th + 3)


def layer_admit(bk, page, img, th):
    W = img.shape[1]
    box = {c["id"]: c for c in _chars(bk, page)}
    tint = img.copy()
    for col in bk.prod("seed_admit", page)["seed_admit"]["columns"]:
        for a in col["chars"]:
            c = box.get(a["id"])
            if c is None:
                continue
            p0, p1 = _rect(c, W)
            if not a.get("admit"):
                cv2.rectangle(img, p0, p1, C["review"], th + 2)
                cv2.rectangle(tint, p0, p1, C["review"], -1)
            elif a.get("channel") == "human":
                cv2.rectangle(tint, p0, p1, C["human"], -1)
            else:
                cv2.rectangle(tint, p0, p1, C["auto"], -1)
    img[:] = blend(img, tint, 0.28)


def layer_free(bk, page, img, th):
    """自由版式：版面块（蓝框，跳过的块灰底）＋ cell_cut 的字框（绿）。坐标左上原点、拉正后的图上。"""
    lb = bk.prod("block_detect", page)["layout_blocks"]
    tint = img.copy()
    for b in lb["blocks"]:
        x0, y0, x1, y1 = map(int, b["box"])
        if b["kind"] == "skip":
            cv2.rectangle(tint, (x0, y0), (x1, y1), (190, 190, 190), -1)
    img[:] = blend(img, tint, 0.5)
    try:
        cells = bk.prod("cell_cut", page)["free_cells"]["cells"]
    except SystemExit:
        cells = []
    for c in cells:
        x0, y0, x1, y1 = map(int, c["box"])
        cv2.rectangle(img, (x0, y0), (x1, y1), C["char"], th)
    for b in lb["blocks"]:
        x0, y0, x1, y1 = map(int, b["box"])
        cv2.rectangle(img, (x0, y0), (x1, y1), C["hline"], th + 3)
        cv2.putText(img, b["label"], (x0 + 10, y0 + 50), cv2.FONT_HERSHEY_SIMPLEX, 1.6, C["hline"], 4)


def layer_ocr(bk, page, img, th):
    """自由版式 line_ocr：识别软件读出的文字行框（橙）。"""
    for ln in bk.prod("line_ocr", page)["free_ocr_lines"]["lines"]:
        pts = np.array(ln["box"], np.int32).reshape(-1, 2)
        if len(pts) == 2:
            (x0, y0), (x1, y1) = pts
            pts = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], np.int32)
        cv2.polylines(img, [pts], True, C["head"], th + 1)


LAYERS = {"border": layer_border, "columns": layer_columns, "cells": layer_cells,
          "shrink": layer_shrink, "seal": layer_seal, "admit": layer_admit,
          "free": layer_free, "ocr": layer_ocr, "chord": layer_chord, "yolo": layer_yolo,
          "tight": layer_tight}


# ---------------------------------------------------------------- 组图

def crop_frac(img, crop):
    if not crop:
        return img
    H, W = img.shape[:2]
    x0, y0, x1, y1 = crop
    return img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]


FREE_LAYERS = {"free", "ocr"}


def page_view(bk, page, layers, crop=None, th=3):
    img = bk.raw(page)
    if FREE_LAYERS & set(layers):
        # 自由版式的产物坐标在「按框线拉正后」的图上（block_detect 的 warp），先拉正再画
        from open_guji_cv.books.zengguang_youxue.free_rectify import rectify_gray
        img = np.ascontiguousarray(rectify_gray(img, bk.prod("block_detect", page)["layout_blocks"].get("warp")))
    for name in layers:
        LAYERS[name](bk, page, img, th)
    return crop_frac(img, crop)


def fit_h(img, h):
    s = h / img.shape[0]
    return cv2.resize(img, (max(1, int(img.shape[1] * s)), h), interpolation=cv2.INTER_AREA)


def fit_w(img, w):
    s = w / img.shape[1]
    return cv2.resize(img, (w, max(1, int(img.shape[0] * s))),
                      interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)


def hstack(imgs, gap=16, h=None):
    h = h or max(i.shape[0] for i in imgs)
    imgs = [fit_h(i, h) for i in imgs]
    out = []
    for i, im in enumerate(imgs):
        if i:
            out.append(np.full((h, gap, 3), 255, np.uint8))
        out.append(im)
    return np.hstack(out)


def vstack(imgs, gap=16):
    w = max(i.shape[1] for i in imgs)
    rows = []
    for i, im in enumerate(imgs):
        if i:
            rows.append(np.full((gap, w, 3), 255, np.uint8))
        pad = np.full((im.shape[0], w - im.shape[1], 3), 255, np.uint8)
        rows.append(np.hstack([im, pad]))
    return np.vstack(rows)


def column_pair(bk, page, col):
    """一列：原图上的那一条（按列窗外接矩形裁）＋ Step2 拉直后的列图。"""
    from open_guji_cv.core.spec import column_key
    raw = bk.raw(page)
    W = raw.shape[1]
    win = {c["col"]: c for c in bk.prod("column_warp", page)["column_windows"]["columns"]}[col]
    xs = [tl(line_x(win[k], y), W)
          for k in ("left_line", "right_line") for y in (win["top_y"], win["bottom_y"])]
    x0, x1 = max(0, min(xs) - 8), min(W, max(xs) + 8)
    strip = raw[int(win["top_y"]):int(win["bottom_y"]), x0:x1]
    warped = bk.materialize("column_image", column_key(page, col))
    return hstack([strip, warped], gap=40)


def cell_crop(bk, page, cid, step, pad=6):
    """一格在原图上的样子：row_segment 的格（四边形外接框）或 cell_shrink 的紧框。"""
    raw = bk.raw(page)
    W = raw.shape[1]
    if step == "row_segment":
        for col in bk.prod("row_segment", page)["cells"]["columns"]:
            for c in col["cells"]:
                key = f'{bk.book}:{page}:{col["col"]}:{c["slot"]}{c.get("sub") or ""}'
                if key == cid:
                    q = _quad(c["quad_page"], W)
                    x0, y0 = q.min(0); x1, y1 = q.max(0)
                    return raw[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad].copy()
    else:
        for c in _chars(bk, page):
            if c["id"] == cid:
                (x0, y0), (x1, y1) = _rect(c, W)
                return raw[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad].copy()
    raise SystemExit(f"找不到格 {cid}（{step}）")


def cell_with_tight(bk, page, cid, pad=6):
    """Step3 的格（外接框）裁出来，叠上 Step4 的紧框（红）。"""
    raw = bk.raw(page)
    W = raw.shape[1]
    q = None
    for col in bk.prod("row_segment", page)["cells"]["columns"]:
        for c in col["cells"]:
            if f'{bk.book}:{page}:{col["col"]}:{c["slot"]}{c.get("sub") or ""}' == cid:
                q = _quad(c["quad_page"], W)
    tight = next((c for c in _chars(bk, page) if c["id"] == cid), None)
    if q is None or tight is None:
        raise SystemExit(f"找不到格 {cid}")
    x0, y0 = q.min(0) - pad; x1, y1 = q.max(0) + pad
    x0, y0 = max(0, x0), max(0, y0)
    img = raw[y0:y1, x0:x1].copy()
    cv2.polylines(img, [q - [x0, y0]], True, C["char"], 2)
    (a0, b0), (a1, b1) = _rect(tight, W)
    cv2.rectangle(img, (a0 - x0, b0 - y0), (a1 - x0, b1 - y0), C["flag"], 2)
    return img


def _patch_stats(im):
    """图块的墨迹统计：外接框高宽、墨占比、贴边墨（被邻字、界行、印压进来的迹象）、碎块数。"""
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
    m = (g < 128).astype(np.uint8)
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    edge = np.concatenate([m[:3].ravel(), m[-3:].ravel(), m[:, :3].ravel(), m[:, -3:].ravel()]).mean()
    n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    specks = int((st[1:, cv2.CC_STAT_AREA] < 6).sum()) if n > 1 else 0
    # 界行、框线残段：横向或竖向贯穿过半个图块的长直墨线
    H, W = m.shape
    rows = max((np.max(np.diff(np.flatnonzero(np.diff(np.r_[0, r, 0])))[::2], initial=0)
                for r in m if r.any()), default=0)
    cols = max((np.max(np.diff(np.flatnonzero(np.diff(np.r_[0, c, 0])))[::2], initial=0)
                for c in m.T if c.any()), default=0)
    line = float(rows > 0.6 * W) + float(cols > 0.85 * H)
    return dict(h=ys.max() - ys.min() + 1, w=xs.max() - xs.min() + 1, ink=m.mean(), edge=edge,
                specks=specks, line=line)


def glyph_examples(ws_data: Path, char: str, n: int, clean: bool = True):
    """字形库里某字的刻例图块（数据目录 output/glyph_store/patches）。

    `clean`：挑干净的——不贴边（没被邻字、界行、印压进来）、碎点少、墨迹高宽和墨量都接近本字中位，
    再按册页均匀取 n 个，免得 Wiki 上看着像切坏了。不挑就按库里顺序取前 n 个。"""
    gs = ws_data / "output" / "glyph_store"
    ids = []
    with open(gs / "exemplars.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["char"] == char:
                ids.append(r["instance_id"])
    cands = []
    for iid in ids:
        # 图块文件名两种写法都有：冒号换成 _（多数）或 ~（bare~ 那批）
        p = next((q for q in (gs / "patches" / (iid.replace(":", s) + ".png") for s in ("_", "~"))
                  if q.exists()), None)
        if p is None:
            continue
        im = cv2.imread(str(p))
        if im is None:
            continue
        cands.append((iid, im))
        if not clean and len(cands) >= n:
            break
    if not clean:
        return [im for _, im in cands]
    st = [(iid, im, _patch_stats(im)) for iid, im in cands]
    st = [t for t in st if t[2]]
    if not st:
        return []
    med = {k: float(np.median([t[2][k] for t in st])) for k in ("h", "w", "ink")}

    def bad(s):
        return (s["edge"] * 50 + s["specks"] * 0.3 + s["line"] * 5
                + sum(abs(s[k] / med[k] - 1) for k in ("h", "w", "ink")))
    good = sorted(st, key=lambda t: bad(t[2]))[:max(n * 3, n)]
    good.sort(key=lambda t: t[0])                      # 按册页排，均匀抽 n 个
    step = len(good) / n if len(good) > n else 1
    return [good[int(i * step)][1] for i in range(min(n, len(good)))]


def frame(img, color=(200, 200, 200), t=2):
    return cv2.copyMakeBorder(img, t, t, t, t, cv2.BORDER_CONSTANT, value=color)


# ---------------------------------------------------------------- 主流程

def render(shot: dict, books: dict, data_dirs: dict) -> np.ndarray:
    kind = shot.get("kind", "page")

    def bk(spec=None):
        spec = spec or shot
        key = (spec["ws"], spec["book"])
        if key not in books:
            books[key] = Book(Path(WS[spec["ws"]]), spec["book"])
        return books[key]

    if kind == "page":
        return page_view(bk(), shot["page"], shot.get("layers", []), shot.get("crop"), shot.get("th", 3))
    if kind == "panels":       # 并排几幅：每幅一个 page 视图；per_row 给了就折成几行
        views = [page_view(bk({**shot, **p}), p.get("page", shot.get("page")), p.get("layers", []),
                           p.get("crop", shot.get("crop")), p.get("th", shot.get("th", 3)))
                 for p in shot["panels"]]
        n = shot.get("per_row") or len(views)
        gap = shot.get("gap", 24)
        return vstack([hstack(views[i:i + n], gap=gap) for i in range(0, len(views), n)], gap=gap)
    if kind == "column":
        return column_pair(bk(), shot["page"], shot["col"])
    if kind == "vline":        # 一条界行附近的竖条，横向放大 xscale 倍看弯：每幅一组图层
        b, page = bk(), shot["page"]
        W = b.raw(page).shape[1]
        bd = b.prod("border_detect", page)["borders"]
        v = bd["verticals"][shot["line"]]
        ys = range(int(bd["top"]["y_at_right"]) - 30, int(bd["bottom"]["y_at_right"]) + 30)
        xs = [tl(line_x(v, y), W) for y in ys]
        hw = shot.get("half", 40)
        x0, x1 = max(0, min(xs) - hw), min(W, max(xs) + hw)
        sx = shot.get("xscale", 3)
        views = []
        for p in shot["panels"]:
            img = page_view(b, page, p.get("layers", []), th=shot.get("th", 1))[ys[0]:ys[-1], x0:x1]
            views.append(cv2.resize(img, (img.shape[1] * sx, img.shape[0]), interpolation=cv2.INTER_NEAREST))
        return hstack(views, gap=shot.get("gap", 24))
    if kind == "cells":        # 几格：每格「Step3 格 | Step4 紧框」或单一种
        b = bk()
        rows = []
        for cid in shot["ids"]:
            page = int(cid.split(":")[1])
            if "steps" in shot:
                imgs = [frame(cell_crop(b, page, cid, s)) for s in shot["steps"]]
            else:          # 缺省：Step3 的格，里面用红框画出 Step4 收出来的紧框
                imgs = [frame(cell_with_tight(b, page, cid))]
            rows.append(hstack(imgs, gap=12, h=shot.get("h", 160)))
        return hstack(rows, gap=36) if shot.get("horizontal") else vstack(rows, gap=24)
    if kind == "glyphs":       # 每字一行：字形库里 n 个刻例
        rows = []
        for ch in shot["chars"]:
            ex = glyph_examples(Path(data_dirs[shot["ws"]]), ch, shot.get("n", 8))
            if not ex:
                raise SystemExit(f"字形库里没有 {ch} 的刻例")
            rows.append(hstack([frame(fit_h(e, 96)) for e in ex], gap=8, h=100))
        return vstack(rows, gap=20)
    raise SystemExit(f"不认识的 kind: {kind}")


def save(img: np.ndarray, path: Path, width: int | None, colors: int):
    if width and img.shape[1] > width:
        img = fit_w(img, width)
    rgb = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    # 调色板量化：影印图多是黑白灰，64 色看不出差别，体积约省六成（Wiki 图都进 git）
    rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


WS: dict[str, str] = {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ws", action="append", default=[], help="书ID=工作区路径，可多次")
    ap.add_argument("--data", action="append", default=[],
                    help="书ID=中心库数据目录（$GUJI_DATA_HOME/<分支>/<ws id>），glyphs 类图要")
    ap.add_argument("--only", action="append", default=[], help="只出这几张（id 前缀）")
    ap.add_argument("--spec", default=str(HERE / "shots.yaml"))
    ap.add_argument("--yolo", help="yolo-tool 仓的 model/ 目录（内含 type/、slide/ 的 best.onnx），yolo 图层要；装 .[yolo]")
    a = ap.parse_args(argv)
    global YOLO_MODEL
    YOLO_MODEL = a.yolo
    for kv in a.ws:
        k, v = kv.split("=", 1); WS[k] = v
    data_dirs = dict(kv.split("=", 1) for kv in a.data)
    spec = yaml.safe_load(open(a.spec, encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    books: dict = {}
    n = 0
    for shot in spec["shots"]:
        if a.only and not any(shot["id"].startswith(p) for p in a.only):
            continue
        if shot.get("ws") not in WS and shot.get("kind") != "glyphs":
            print(f"跳过 {shot['id']}：没给 --ws {shot.get('ws')}=…", file=sys.stderr)
            continue
        img = render(shot, books, data_dirs)
        path = OUT / f"{shot['id']}.png"
        save(img, path, shot.get("width", spec.get("width", 1000)), shot.get("colors", 64))
        n += 1
        print(f"{path.relative_to(HERE.parent.parent)}  {path.stat().st_size // 1024} KB")
    print(f"出了 {n} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
