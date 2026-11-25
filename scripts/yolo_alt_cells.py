# -*- coding: utf-8 -*-
"""yolo_tool 框字 + 小注分类器 → 整列备选格表（`row_segment.alt_cuts` 读的那张，行里带 `cells`）。

    # 1. 训小注分类器（读一个工作区里几册的 row_segment、seed_admit 产物，拿放行格当样本）
    python scripts/yolo_alt_cells.py train -w <工作区> --books 02,03,04,05 --out jzcls.pt
    # 2. 出表
    python scripts/yolo_alt_cells.py gen -w <工作区> --book 01 --model-dir <yolo_tool>/model \
        --note-model jzcls.pt --out <表.jsonl> [--pages 5-7]

一行一列（格式同 manual-cells）：

    {"vol": "01", "page": 7, "col": 7, "col_h": 3244, "cells": [{"slot": 1, "sub": null, "kind": "char",
     "x0": 5.0, "x1": 203.0, "y0": 4.0, "y1": 196.0}, …, {"slot": 9, "sub": "a", "kind": "jiazhu_a", …}]}

为什么（2026-11-20 脉经 01，MJ，GUJI-774）：正文按 20 格等距切，字高不匀就逐格错位；`yolo_alt_cuts.py`
的格线表能救大字列，但有雙行小注的列它不写。这张表整列写定：
- 大字：列图喂 yolo_tool slide 模型（conf 0.25、NMS 0.45），框按中心 y 排，`yolo_alt_cuts.clean` 去噪、并劈开的高字；
  列首／列尾的横条（版框线）和太矮的残块丢掉——只丢两端，中间的「一」「少」这类扁字也是一条横，不能丢；
- 小注：YOLO 常把并排两小字框成一框，所以每框过一个小 CNN（内容宽 × 框高缩 32×32，判「小注行 vs 大字」）。
  连续小注框成一段；段内找两行之间的白缝（中间 40% 宽里墨最少的竖线），左右两半各自再喂 YOLO 框字，格放在相邻框之间。
  挨着小注框、墨宽不到内容宽 72% 的框也算小注（一行只剩一字的末格）。
  分类器判是、但框比正文一格（列高／每列字数）高出 40% 以上的不算小注起点：YOLO 把两个扁大字并成一个高框时分类器会摇摆（01 16:6「定息」）。
- 相邻两单元之间取中点作格界；格子满内容宽（裁图时由 `cell_shrink.manual_ink_fit` 收到格内墨迹再裁，不带进邻字）。

分类器：3 层卷积，1 通道 32×32，二分类；样本是放行格（大字格 → 0；同 slot 的 a、b 都放行、纵向叠 ≥60% 的小注行 → 1）。
脉经 02–05 训、01 测：阈 0.5 召回 0.995，9,848 个大字格误判 5 个。训一遍 CPU 一两分钟，种子固定，可重建，不进模型表。

只作备选：row_segment 照常切主切法，表里这列和主切法墨迹不同才作备选列，下游按列挑（`align_ref.alt_select: admit`、
`context_decide.alt_columns`）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yolo_alt_cuts import clean  # noqa: E402

PATCH = 32
P_NOTE = 0.5


def note_net():
    import torch.nn as nn
    return nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                         nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                         nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d(4), nn.Flatten(),
                         nn.Linear(512, 64), nn.ReLU(), nn.Linear(64, 1))


def patch32(img, y0, y1, cx0, cx1, pad=0):
    import cv2
    y0, y1 = max(0, int(y0) - pad), min(img.shape[0], int(y1) + pad)
    p = img[y0:y1, int(cx0):int(cx1)]
    if p.size == 0:
        return None
    return cv2.resize(p, (PATCH, PATCH), interpolation=cv2.INTER_AREA)


class NoteCls:
    def __init__(self, path: str):
        import torch
        self.torch = torch
        self.m = note_net()
        self.m.load_state_dict(torch.load(path, map_location="cpu"))
        self.m.eval()

    def prob(self, img, y0, y1, cx0, cx1) -> float:
        p = patch32(img, y0, y1, cx0, cx1, pad=6)
        if p is None:
            return 0.0
        x = (255 - p.astype(np.float32)) / 255.0
        with self.torch.no_grad():
            return float(self.torch.sigmoid(self.m(self.torch.tensor(x)[None, None])).item())


class _Box:
    def __init__(self, x0, y0, x1, y1, conf=1.0):
        self.x0, self.y0, self.x1, self.y1, self.conf = x0, y0, x1, y1, conf


def channel_x(img, y0, y1, cx0, cx1) -> int:
    """雙行小注两行之间的白缝：内容宽中间 40% 里（5 像素平滑后）墨最少的竖线。"""
    w = cx1 - cx0
    xa, xb = int(cx0 + .3 * w), int(cx0 + .7 * w)
    ink = (img[int(y0):int(y1), xa:xb] < 128).sum(0).astype(float)
    return xa + int(np.argmin(np.convolve(ink, np.ones(5) / 5, "same")))


def _detect(yt, img):
    import cv2
    return yt._detect(yt.slide_sess, cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 0.25, 0.45, None)


def sub_boxes(yt, img, y0, y1, x0, x1, pad=0):
    """小注一行（x0..x1）里框字：上下各外扩 pad 喂 YOLO，留中心落在 y0..y1 的框，纵向叠过半的并，丢碎块。"""
    Y0, Y1 = max(0, int(y0 - pad)), min(img.shape[0], int(y1 + pad))
    crop = img[Y0:Y1, int(x0):int(x1)]
    if crop.size == 0:
        return []
    bs = [_Box(b.x0 + x0, b.y0 + Y0, b.x1 + x0, b.y1 + Y0, b.conf) for b in _detect(yt, crop) if (b.y1 - b.y0) >= 12]
    bs = sorted((b for b in bs if y0 <= (b.y0 + b.y1) / 2 <= y1), key=lambda b: (b.y0 + b.y1) / 2)
    out: list[list[float]] = []
    for b in bs:
        if out and min(out[-1][3], b.y1) - max(out[-1][1], b.y0) > 0.5 * min(out[-1][3] - out[-1][1], b.y1 - b.y0):
            a = out[-1]
            out[-1] = [min(a[0], b.x0), min(a[1], b.y0), max(a[2], b.x1), max(a[3], b.y1)]
        else:
            out.append([b.x0, b.y0, b.x1, b.y1])
    if out:
        med = np.median([(q[2] - q[0]) * (q[3] - q[1]) for q in out])
        out = [q for q in out if (q[2] - q[0]) * (q[3] - q[1]) >= 0.25 * med]
    return out


def column_cells(yt, cls: NoteCls, img, cx0: float, cx1: float, p_note: float = P_NOTE, per_col: int = 20):
    """一列 → manual-cells 格式的格表；框不到字返回 None。"""
    H, W = img.shape[0], cx1 - cx0
    raw = sorted(_detect(yt, img), key=lambda b: (b.y0 + b.y1) / 2)
    if not raw:
        return None
    med_a = float(np.median([(b.x1 - b.x0) * (b.y1 - b.y0) for b in raw]))
    raw = [b for b in raw if (b.x1 - b.x0) * (b.y1 - b.y0) >= 0.08 * med_a]
    pr = [cls.prob(img, b.y0, b.y1, cx0, cx1) for b in raw]
    ink = img < 128

    def ink_w(b):
        xs = np.where(ink[int(b.y0):int(b.y1), int(cx0):int(cx1)].sum(0) > 1)[0]
        return (xs.max() - xs.min()) if xs.size else 0

    def is_bar(b):
        rows = ink[int(b.y0):int(b.y1), int(cx0):int(cx1)].mean(1)
        return bool(rows.size) and rows.max() > .7 and (rows > .1).sum() < .35 * rows.size

    hs = sorted(b.y1 - b.y0 for b in raw)
    mh = hs[len(hs) // 2]
    # 小注起点：分类器判是、且不比大字高出许多（YOLO 把两个扁大字并成一个高框时分类器会摇摆，01 16:6「定息」）
    big_h = H / per_col        # 正文一格高；小注多的列 mh 是小注高，不能拿来比
    isn = [q > p_note and (b.y1 - b.y0) < 1.4 * big_h for q, b in zip(pr, raw)]
    for i, b in enumerate(raw):          # 小注段的续行：挨着小注框、半宽、概率不太低
        if not isn[i] and pr[i] > .2 and ink_w(b) < .72 * W and (
                (i > 0 and isn[i - 1]) or (i + 1 < len(raw) and isn[i + 1])):
            isn[i] = True
    ends = (0, len(raw) - 1)
    keep = [not (i in ends and (is_bar(b) or (b.y1 - b.y0) < .45 * mh)) for i, b in enumerate(raw)]
    raw = [b for b, k in zip(raw, keep) if k]
    isn = [n for n, k in zip(isn, keep) if k]
    units: list[tuple[str, object]] = []
    for b, n in zip(raw, isn):
        if n and units and units[-1][0] == "note":
            units[-1][1].append(b)
        else:
            units.append(("note", [b]) if n else ("big", b))
    out_units: list[tuple[str, list[float]]] = []
    run: list = []

    def flush():
        out_units.extend(("big", q) for q in clean(run))
        run.clear()

    for k, v in units:
        if k == "big":
            run.append(v)
        else:
            flush()
            out_units.append(("note", [min(b.y0 for b in v), max(b.y1 for b in v)]))
    flush()
    if not out_units:
        return None
    spans = [(u[1][1], u[1][3]) if u[0] == "big" else (u[1][0], u[1][1]) for u in out_units]
    bounds = ([max(0.0, spans[0][0] - 8)] + [(a[1] + b[0]) / 2 for a, b in zip(spans, spans[1:])]
              + [min(float(H), spans[-1][1] + 8)])
    cells: list[dict] = []
    slot = 1
    for i, u in enumerate(out_units):
        t, bt = bounds[i], bounds[i + 1]
        if u[0] == "big":
            cells.append({"slot": slot, "sub": None, "kind": "char", "x0": float(cx0), "x1": float(cx1),
                          "y0": round(t, 1), "y1": round(bt, 1)})
            slot += 1
            continue
        xm = channel_x(img, u[1][0], u[1][1], cx0, cx1)
        A = sub_boxes(yt, img, t, bt, xm, cx1, 0.5 * mh)
        B = sub_boxes(yt, img, t, bt, cx0, xm, 0.5 * mh)
        if not A and not B:
            A = [[xm, u[1][0], cx1, u[1][1]]]
        for sub, bx, x0, x1 in (("a", A, xm, cx1), ("b", B, cx0, xm)):
            ys = [t] + [(p[3] + q[1]) / 2 for p, q in zip(bx, bx[1:])] + [bt]
            for j, (y0, y1) in enumerate(zip(ys, ys[1:])):
                cells.append({"slot": slot + j, "sub": sub, "kind": "jiazhu_" + sub, "x0": float(x0), "x1": float(x1),
                              "y0": round(y0, 1), "y1": round(y1, 1)})
        slot += max(len(A), len(B))
    return cells


def _row_segment_pages(book: str, pages):
    for f in sorted(Path("products", book, "row_segment").glob("p*.json")):
        page = int(f.stem[1:])
        if pages is not None and page not in pages:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        yield page, (d if "columns" in d else d[next(iter(d))])


def _ctx(book: str):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products import kinds as _k  # noqa: F401
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    ctx = RunContext(load_book(book), ProductStore(), ImageCache(), log=lambda s: None)
    ctx.step_id = "row_segment"
    return ctx


def cmd_gen(a) -> None:
    from open_guji_cv.core.book import _expand_pages
    from open_guji_cv.core.spec import column_key
    from open_guji_cv.impl.keben.yolo_tool_infer import YoloTool
    pages = set(_expand_pages(a.pages)) if a.pages else None
    yt, cls, ctx = YoloTool(a.model_dir), NoteCls(a.note_model), _ctx(a.book)
    rows, n_note = [], 0
    for page, d in _row_segment_pages(a.book, pages):
        for col in d["columns"]:
            if not col.get("content_x") or not col["cells"] or "roster" in (col.get("flags") or []):
                continue
            img = ctx.image("column_image", column_key(page, col["col"]))
            img = img if img.ndim == 2 else img[..., 0]
            cells = column_cells(yt, cls, img, *col["content_x"], per_col=ctx.book.chars_per_line or 20)
            if not cells:
                continue
            n_note += any(c["sub"] for c in cells)
            rows.append({"vol": a.book, "page": page, "col": col["col"], "col_h": int(img.shape[0]), "cells": cells})
    Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(a.book, f"{len(rows)} 列（其中带小注 {n_note}）→", a.out)


def cmd_train(a) -> None:
    import torch
    import torch.nn as nn
    from open_guji_cv.core.spec import column_key
    X, Y = [], []
    for book in a.books.split(","):
        ctx = _ctx(book)
        for page, rs in _row_segment_pages(book, None):
            sa = Path("products", book, "seed_admit", f"p{page:04d}.json")
            if not sa.exists():
                continue
            s = json.loads(sa.read_text(encoding="utf-8"))
            s = s if "columns" in s else s[next(iter(s))]
            adm = {(c["col"], x["slot"], x.get("sub")): x["admit"] for c in s["columns"] for x in c["chars"]}
            for col in rs["columns"]:
                if "roster" in (col.get("flags") or []) or not col.get("content_x"):
                    continue
                img = None
                by: dict[int, dict] = {}
                for c in col["cells"]:
                    by.setdefault(c["slot"], {})[c.get("sub")] = c
                for slot, d in by.items():
                    if None in d and d[None]["kind"] == "char" and adm.get((col["col"], slot, None)):
                        y0, y1, lab = d[None]["y0"], d[None]["y1"], 0
                    elif "a" in d and "b" in d and adm.get((col["col"], slot, "a")) and adm.get((col["col"], slot, "b")):
                        A, B = d["a"], d["b"]
                        if min(A["y1"], B["y1"]) - max(A["y0"], B["y0"]) < 0.6 * min(A["y1"] - A["y0"], B["y1"] - B["y0"]):
                            continue
                        y0, y1, lab = min(A["y0"], B["y0"]), max(A["y1"], B["y1"]), 1
                    else:
                        continue
                    if y1 - y0 < 20:
                        continue
                    if img is None:
                        img = ctx.image("column_image", column_key(page, col["col"]))
                        img = img if img.ndim == 2 else img[..., 0]
                    p = patch32(img, y0, y1, *col["content_x"])
                    if p is not None:
                        X.append(p)
                        Y.append(lab)
    X = (255 - np.array(X, np.float32)) / 255.0
    Y = np.array(Y)
    print("样本", len(Y), "小注", int(Y.sum()))
    torch.manual_seed(0)
    m = note_net()
    opt = torch.optim.Adam(m.parameters(), 1e-3)
    xt, yt = torch.tensor(X)[:, None], torch.tensor(Y, dtype=torch.float32)
    lossf = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([(Y == 0).sum() / max(1, (Y == 1).sum())]).sqrt())
    for _ep in range(a.epochs):
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), 256):
            j = perm[i:i + 256]
            opt.zero_grad()
            lossf(m(xt[j]).squeeze(1), yt[j]).backward()
            opt.step()
    torch.save(m.state_dict(), a.out)
    print("→", a.out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("gen", help="出备选格表")
    g.add_argument("-w", "--workspace", required=True)
    g.add_argument("--book", required=True)
    g.add_argument("--model-dir", required=True, help="yolo_tool 的 model/ 目录（含 slide/best.onnx）")
    g.add_argument("--note-model", required=True, help="train 训出的小注分类器 state_dict")
    g.add_argument("--out", required=True)
    g.add_argument("--pages", default="", help="页号表达式，如 5-7,16；缺省整册")
    t = sp.add_parser("train", help="训小注分类器")
    t.add_argument("-w", "--workspace", required=True)
    t.add_argument("--books", required=True, help="逗号分隔的册，读它们的 row_segment、seed_admit 产物")
    t.add_argument("--epochs", type=int, default=6)
    t.add_argument("--out", required=True)
    a = ap.parse_args()
    os.environ.setdefault("GUJI_WORKSPACE", a.workspace)
    a.out = str(Path(a.out).resolve())
    if getattr(a, "note_model", None):
        a.note_model = str(Path(a.note_model).resolve())
    os.chdir(a.workspace)
    (cmd_gen if a.cmd == "gen" else cmd_train)(a)


if __name__ == "__main__":
    main()
