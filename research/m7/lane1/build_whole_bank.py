# -*- coding: utf-8 -*-
"""呂吕、徵徴 整字判法的模板库：殿本人裁 confirm 事件 → 字块灰度图 → `config/groups/<组>/ids_bank.json`（含按册留一评测）。

    python research/m7/lane1/build_whole_bank.py <feedback 根> <原图根(含 volNN/<页>.png)> [--write] [--out-root 仓根]

- 事件：`feedback/events/*.jsonl` 里 `payload.shape` ∈ 组内字的 confirm（sheldon 看图裁的刻形）。同一格多条且字不一致的整格丢弃。
- 字块图：事件锚点带 `content_sha` 且 `feedback/anchor_patches/<册>/<sha前2>/<sha>.png` 在 → 用当时的 Step4 字块（和线上同源）；
  没有就按锚点 bbox 从原图裁（`raw_page_px@top-right`，x'=W−1−x），去掉贴边的邻字残影与散点，Otsu 二值，再当灰度用。
- 默认只评测、只打印；`--write` 才写模板库。扩池后重跑，换了库内容 `seed_admit` 的 group_flow 指纹会变（开了这两组的册判过期）。
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from open_guji_cv.groups import ids_online, ids_whole  # noqa: E402

GROUPS = {"lv": "呂吕", "zheng": "徵徴"}


def clean(gray: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = b > 0
    if b.mean() > 0.5:      # 黑底白字的裁图（页边）：反相
        b = ~b
    h, w = b.shape
    lab, n = ndi.label(b, structure=np.ones((3, 3)))
    keep = np.zeros_like(b)
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        m = lab[sl] == i
        cy, cx = (sl[0].start + sl[0].stop) / 2, (sl[1].start + sl[1].stop) / 2
        if m.sum() < 12:
            continue
        if (cx < 0.08 * w or cx > 0.92 * w or cy < 0.05 * h) and m.sum() < 0.03 * h * w:
            continue
        keep[sl] |= m
    return np.where(keep, 0, 255).astype(np.uint8)


def collect(fb: Path, raw: Path):
    ledger = {}
    for f in glob.glob(str(fb / "anchors" / "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            x = json.loads(line)
            if x.get("anchor"):
                ledger[x["key"]] = x["anchor"]
    shapes: dict = {}
    for f in sorted(glob.glob(str(fb / "events" / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            s = (e.get("payload") or {}).get("shape")
            t = e.get("target") or {}
            if e.get("kind") == "confirm" and s in set("".join(GROUPS.values())) and t.get("key"):
                shapes.setdefault(t["key"], []).append((s, e))
    cells, cache = [], {}
    for key, lst in sorted(shapes.items()):
        if len({s for s, _ in lst}) > 1:
            continue
        s, e = lst[-1]
        t = e["target"]
        a = t.get("anchor") or ledger.get(key)
        if not a or not a.get("bbox"):
            continue
        book, page = t["book"], t["page"]
        sha = a.get("content_sha")
        pp = fb / "anchor_patches" / book / sha[:2] / f"{sha}.png" if sha else None
        if pp is not None and pp.exists():
            gray = cv2.imread(str(pp), cv2.IMREAD_GRAYSCALE)
        else:
            if (book, page) not in cache:
                cache = {(book, page): cv2.imread(str(raw / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)}
            g = cache[(book, page)]
            if g is None:
                continue
            x0, y0, x1, y1 = a["bbox"]
            w = g.shape[1]
            crop = g[max(0, int(y0)):int(y1), max(0, int(round(w - 1 - x1))):int(round(w - 1 - x0))]
            if crop.size == 0:
                continue
            gray = clean(crop)
        cells.append((s, gray, book, key))
    return cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feedback", type=Path)
    ap.add_argument("raw", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out-root", type=Path, default=ROOT)
    a = ap.parse_args()
    cells = collect(a.feedback, a.raw)
    for g, mem in GROUPS.items():
        sp = ids_online.SPECS[g]
        cs = [c for c in cells if c[0] in mem]
        bank = ids_whole.build(g, cs, sp.size, {"pool": "殿本人裁 confirm 事件（中心库 feedback/events）+ 锚点字块／原图锚点裁"})
        r = ids_whole.evaluate(g, bank)
        print(g, mem, "格", r["cells"], {f: len(v) for f, v in bank["templates"].items()}, "册", sorted({b for v in bank["source"]["books"].values() for b in v}))
        for m, c in r["by_margin"].items():
            print(f"  |d|≥{m}: {c}")
        print("  不设门槛错例", r["wrong"])
        if a.write:
            out = a.out_root / "config" / "groups" / g / "ids_bank.json"
            ids_online.write_bank(bank, out)
            print("  写入", out)


if __name__ == "__main__":
    main()
