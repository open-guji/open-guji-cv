# -*- coding: utf-8 -*-
"""yolo_tool 单字模型在列图上框字 → 备选格线表（`row_segment.alt_cuts` 读的那张）。

    python scripts/yolo_alt_cuts.py -w <工作区> --book 01 --model-dir <yolo_tool>/model --out <表.jsonl> [--pages 5-7,16]

先跑过本册 row_segment（读它的产物定每列正文格数、跳过的列）。一行一列：

    {"vol": "01", "page": 7, "col": 7, "cuts": [0.0, 196.6, …, 3175.0], "col_h": 3175, "n_boxes": 20}

做法（2026-11-20 脉经 01 7:7「景之書并」被等距格切成 5 格，MJ，GUJI-774）：
- 列图喂 yolo_tool 的 slide 模型（conf 0.25、NMS 0.45），框按中心 y 排；
- 去噪：面积不到中位 8% 的点；夹在上下两框之间、和两边都叠着的矮框（字的一部分被另框一次）；
  和上一框纵向重叠 ≥40% 的并成一框（「書」下半「日」）；首末不到 0.45 个字高的框（版框线）；
  相邻两矮框合起来不超过 1.3 个字高的并成一框（「衰」被劈成「士」「辰」）；
- 格线放在相邻两框之间；首框上方空着 ≥0.6 个字高的按字高补空格（低两三格起的题行）；
  框数少于正文格数的短列，末字下的空白均分成空格；框加空格多于正文格数的列不写。
- 有雙行小注（jiazhu_*）或抬头格（slot≤0）的列不写（YOLO 对小注不可靠）。

高字被劈成两框（聾→龍耳）去噪抓不全，所以这张表只作备选，下游按列挑（`align_ref.alt_select: admit`）。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np


def clean(bs):
    bs = sorted(bs, key=lambda b: (b.y0 + b.y1) / 2)
    if not bs:
        return []
    med_a = float(np.median([(b.x1 - b.x0) * (b.y1 - b.y0) for b in bs]))
    bs = [b for b in bs if (b.x1 - b.x0) * (b.y1 - b.y0) >= 0.08 * med_a]
    if not bs:
        return []
    med_h = float(np.median([b.y1 - b.y0 for b in bs]))
    keep = []
    for i, b in enumerate(bs):
        h = b.y1 - b.y0
        ov = sum(max(0.0, min(b.y1, o.y1) - max(b.y0, o.y0)) for o in bs[max(0, i - 1):i] + bs[i + 1:i + 2])
        if h < 0.8 * med_h and ov >= 0.35 * h and b.conf < 0.8:
            continue
        keep.append(b)
    out: list[list[float]] = []
    for b in keep:
        if out:
            a = out[-1]
            ov = min(a[3], b.y1) - max(a[1], b.y0)
            if ov > 0.4 * min(a[3] - a[1], b.y1 - b.y0):
                out[-1] = [min(a[0], b.x0), min(a[1], b.y0), max(a[2], b.x1), max(a[3], b.y1)]
                continue
        out.append([b.x0, b.y0, b.x1, b.y1])
    if len(out) >= 3:
        med = float(np.median([b[3] - b[1] for b in out]))
        while out and out[-1][3] - out[-1][1] < 0.45 * med:
            out.pop()
        while out and out[0][3] - out[0][1] < 0.45 * med:
            out.pop(0)
        i = 0
        while i + 1 < len(out):
            p, q = out[i], out[i + 1]
            if (min(p[3] - p[1], q[3] - q[1]) < 0.75 * med and q[3] - p[1] <= 1.3 * med
                    and q[1] - p[3] < 0.15 * med):
                out[i] = [min(p[0], q[0]), p[1], max(p[2], q[2]), q[3]]
                del out[i + 1]
            else:
                i += 1
    return out


def column_cuts(boxes, n_body: int, col_h: int):
    """去噪后的字框 → 格线（n_body+1 条）；排不下返回 None。"""
    if not boxes:
        return None
    pitch = float(np.median([b[3] - b[1] for b in boxes])) * 1.05
    lead = int(round(boxes[0][1] / pitch)) if boxes[0][1] > 0.6 * pitch else 0
    if len(boxes) + lead > n_body:
        return None
    top = boxes[0][1] - 0.1 * pitch
    cuts = [round(top * i / lead, 1) for i in range(lead)] if lead else []
    cuts += [round(top, 1) if lead else 0.0] + [round((a[3] + b[1]) / 2, 1) for a, b in zip(boxes, boxes[1:])]
    k = n_body - len(boxes) - lead
    if k:
        y = boxes[-1][3] + 0.1 * pitch
        if col_h - y < 0.6 * pitch * k:
            return None
        step = (col_h - y) / k
        cuts += [round(y + i * step, 1) for i in range(k)]
    cuts.append(float(col_h))
    if any(b <= a for a, b in zip(cuts, cuts[1:])):
        return None
    return cuts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--model-dir", required=True, help="yolo_tool 的 model/ 目录（含 type/、slide/ 的 best.onnx）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="", help="页号表达式，如 5-7,16；缺省整册")
    a = ap.parse_args()
    os.environ.setdefault("GUJI_WORKSPACE", a.workspace)
    os.chdir(a.workspace)
    import cv2
    from open_guji_cv.core.book import _expand_pages, load_book
    from open_guji_cv.core.spec import column_key
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.impl.keben.yolo_tool_infer import YoloTool
    from open_guji_cv.products import kinds as _k  # noqa: F401
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    pages = set(_expand_pages(a.pages)) if a.pages else None
    yt = YoloTool(a.model_dir)
    ctx = RunContext(load_book(a.book), ProductStore(), ImageCache(), log=lambda s: None)
    ctx.step_id = "row_segment"
    stats = {"cols": 0, "written": 0, "skip_note_or_raised": 0, "no_fit": 0}
    rows = []
    for f in sorted(Path("products", a.book, "row_segment").glob("p*.json")):
        page = int(f.stem[1:])
        if pages is not None and page not in pages:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        d = d if "columns" in d else d[next(iter(d))]
        for col in d["columns"]:
            cells = col["cells"]
            if not cells:
                continue
            stats["cols"] += 1
            if any((x.get("kind") or "").startswith("jiazhu") or x["slot"] <= 0 for x in cells):
                stats["skip_note_or_raised"] += 1
                continue
            img = ctx.image("column_image", column_key(page, col["col"]))
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
            boxes = clean(yt._detect(yt.slide_sess, bgr, 0.25, 0.45, None))
            cuts = column_cuts(boxes, max(x["slot"] for x in cells), img.shape[0])
            if cuts is None:
                stats["no_fit"] += 1
                continue
            stats["written"] += 1
            rows.append({"vol": a.book, "page": page, "col": col["col"], "cuts": cuts,
                         "col_h": int(img.shape[0]), "n_boxes": len(boxes)})
    Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(a.book, stats, "→", a.out)


if __name__ == "__main__":
    main()
