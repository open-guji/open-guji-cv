"""长尾线（2026-10-21）：从殿本整册产物里收「整理本与库一致、通道 match_ref」的放行格，做子于（zy）、山由出（sy）整字模板库。

用法：python build_bank.py <产物根，含 volNN/volNN/> <原图根 data_full/zongmu> <组 id> [输出目录]
标签＝放行字（match_ref：库匹配的字与整理本对位字一致）；不是人裁真值，评测里的「错」要逐个看图。
每类最多 `CAP` 个（按册均匀随机、种子固定），模板库大小压在 1MB 内；评测是按册留一（`ids_whole.evaluate`）。
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups import ids_whole


def gather(prod: Path, imgs: Path, chars: str, size: int, channels=("match_ref",)):
    out = []   # (字, 册, id, 归一图)
    for vd in sorted(glob.glob(str(prod / "vol*"))):
        book = Path(vd).name
        by_page: dict = {}
        for f in glob.glob(f"{vd}/{book}/seed_admit/p*.json"):
            for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                for r in col["chars"]:
                    if r["char"] and r["char"] in chars and r["admit"] and r["channel"] in channels and not r["doubts"]:
                        by_page.setdefault(int(Path(f).stem[1:]), []).append(r)
        for page, rs in sorted(by_page.items()):
            cs = json.load(open(f"{vd}/{book}/cell_shrink/p{page:04d}.json", encoding="utf-8"))["char_index"]["columns"]
            box = {ch["id"]: ch["bbox_page"] for col in cs for ch in col["chars"]}
            img = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
            for r in rs:
                if box.get(r["id"]) is None:
                    continue
                g = crop_patch(img, tuple(box[r["id"]]))
                x = None if g is None else ids_whole.norm(g, size)
                if x is not None:
                    out.append((r["char"], book, r["id"], x))
    return out


#: 组 → (进模板库的字, 归一边长, 每类上限)。组外的 干、曲 也进库：判成它们就 abstain:slot，免得真的干／曲被硬判成组内字。与 `ids_online.SPECS` 里的 size 一致。
PLAN = {"zy": ("子于干", 32, 250), "sy": ("山由出曲", 40, 150),
        "sz": ("宋朱未末", 40, 100), "gm": ("各名", 40, 200), "xb": ("心必", 32, 250)}


def pick(cells, cap: int, seed: int = 0):
    """每类最多 cap 个，固定种子随机抽，保持原顺序。"""
    rng = np.random.default_rng(seed)
    keep = set()
    for c in sorted({x[0] for x in cells}):
        idx = [i for i, x in enumerate(cells) if x[0] == c]
        if len(idx) > cap:
            idx = rng.choice(idx, cap, replace=False)
        keep |= set(int(i) for i in idx)
    return [x for i, x in enumerate(cells) if i in keep]


if __name__ == "__main__":
    from open_guji_cv.groups import ids_online as O

    prod, imgs, g = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    dst = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("config/groups") / g
    chars, size, cap = PLAN[g]
    cells = pick(gather(prod, imgs, chars, size), cap)
    # 评测与建库同一量化：建库时 norm 过一次，这里直接用归一图
    tpl: dict = {}
    books: dict = {}
    keys: dict = {}
    for f, b, k, x in cells:
        tpl.setdefault(f, []).append(x)
        books.setdefault(f, []).append(b)
        keys.setdefault(f, []).append(k)
    d = O.dump_bank(g, tpl, {"labels": "殿本 vol04–10 seed_admit 放行格（channel=match_ref、无疑问）", "cap": cap,
                             "books": {k: books[k] for k in sorted(books)}, "keys": {k: keys[k] for k in sorted(keys)},
                             "cells": len(cells)}, size=size)
    O.write_bank(d, dst / "ids_bank.json")
    from open_guji_cv.groups import ids_whole
    sp = O.SPECS[g]
    r = ids_whole.evaluate(g, d, margins=(0.2, sp.min_margin, 1.0))
    print(g, {k: len(v) for k, v in tpl.items()}, r["by_margin"], r["wrong"][:20])
