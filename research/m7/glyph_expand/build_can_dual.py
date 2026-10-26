"""參㕘叅 两路一致判法建库与按册留出（2026-10-26，A24「压低參㕘叅送审」）。

    python build_can_dual.py <原图根> <数据目录> <产物根> <标注表 jsonl> <char_patch 目录> [--write] [--cap=150] [--size=32]

标注表一行 `{id, form}`（form ∈ 㕘叅，看图标的刻形：钩右边一笔＝㕘，一点一撇两笔＝叅）；參 取已放行格（每册 ≤`PER_VOL`、总共 ≤cap，IDS 判 參 全书无错）。
字块一律用线上同款 char_patch（`<char_patch 目录>/<册>_<页>_<列>_<格>.png`，`research/m7/bench/materialize_patches.py` 现算）。
两个模板库：`ids_bank.json`＝自动缝切下段再第二刀取最下一小块（彡／小／𠇍，与 `ids_two.part_of(…, sub_prior)` 同取法，用原字块）；
`whole_bank.json`＝整字（`ids_whole.clean_patch` 去碎墨后）HOG 岭回归的模板。按册留出：判某册时两库都不含该册。
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import build_shape_pair as B  # noqa: E402

from open_guji_cv.groups import ids_online as O, ids_two as T, ids_whole as W  # noqa: E402
from open_guji_cv.groups.ids_parts import PART_SIZE, similarity  # noqa: E402

SLOT = {"參": "彡", "㕘": "小", "叅": "𠇍"}
#: 标注表里与 sheldon 早先人裁不一致的格（看图像 叅、他标 㕘），不进模板
DROP = {"vol09:3:6:7", "vol04:47:1:6"}


def load(imgs, data, prods, lab, cp, cap):
    extra = {k: f for k, f in B.labels_extra(Path(lab)).items() if k not in DROP}
    raw = lambda k: cv2.imread(str(Path(cp) / (k.replace(":", "_") + ".png")), cv2.IMREAD_GRAYSCALE)
    cells = B.gather([prods], Path(imgs), Path(data), "參", extra, DROP, "can", lambda b, k: raw(k))
    random.seed(0)
    can = [c for c in cells if c[0] == "參"]
    keep = set(c[3] for c in random.sample(can, min(cap, len(can))))
    out = []
    for f, clean, b, k in cells:
        if f == "參" and k not in keep:
            continue
        g = raw(k)
        pl = T.auto_cut(g, "h", 0.52)
        part = T.part_of(g, pl, "h", 1, 0.45) if pl is not None else None
        if part is None:
            continue
        out.append((f, b, k, O.quantize(part).astype(np.float32) / 255.0, clean))
    return out


def judge(x, ibank, wbank, size):
    sc = {n: max(similarity(x[3], t) for t in ts) for n, ts in ibank.items() if ts}
    r = sorted(sc.items(), key=lambda z: -z[1])
    ic = {v: k for k, v in SLOT.items()}[r[0][0]]
    wc, wm, _ = W.score_norm(W.norm(np.asarray(x[4]), size), wbank, "hog", (0.0, 1.0, 0.0, 1.0), 1.0)
    return ic, r[0][1] - r[1][1], wc, wm


def loo(X, size):
    res = []
    for bk in sorted({x[1] for x in X}):
        ib, wb = defaultdict(list), defaultdict(list)
        for x in X:
            if x[1] != bk:
                ib[SLOT[x[0]]].append(x[3])
                wb[x[0]].append(W.norm(np.asarray(x[4]), size))
        for x in X:
            if x[1] == bk:
                res.append((x[0], x[2], *judge(x, ib, wb, size)))
    return res


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    kv = dict(x[2:].split("=", 1) for x in sys.argv[1:] if x.startswith("--") and "=" in x)
    cap, size = int(kv.get("cap", 150)), int(kv.get("size", 32))
    X = load(*a[:5], cap)
    print("模板", Counter(x[0] for x in X), "册", len({x[1] for x in X}))
    res = loo(X, size)
    for wa in (0.3, 0.4, 0.5):
        for ia in (0.03, 0.04, 0.05, 0.06):
            give = [r for r in res if r[2] == r[4] and r[5] >= wa and r[3] >= ia]
            wr = [(r[1], r[0], "→", r[2], round(r[3], 3), round(r[5], 2)) for r in give if r[2] != r[0]]
            print(f"  整字≥{wa} IDS≥{ia}: 给 {len(give)}/{len(res)} 错 {len(wr)}", dict(Counter(r[2] for r in give if r[2] == r[0])), wr[:4])
    json.dump(res, open(kv.get("dump", "/tmp/can_dual_loo.json"), "w"), ensure_ascii=False)
    if "--write" in sys.argv:
        d = Path(__file__).resolve().parents[3] / "config" / "groups" / "can"
        src = {"labels": "dataset char-groups/variant/can/claude_labels_1026.jsonl（看图刻形 㕘／叅）＋已放行 參", "cells": len(X),
               "forms": dict(Counter(x[0] for x in X))}
        ib, wb = defaultdict(list), defaultdict(list)
        for x in X:
            ib[SLOT[x[0]]].append(x[3])
            wb[x[0]].append(W.norm(np.asarray(x[4]), size))
        O.write_bank(O.dump_bank("can", ib, {**src, "part": "自动缝 0.52 → 第二刀 0.45 取最下块"}, PART_SIZE), d / "ids_bank.json")
        O.write_bank(W.build("can", [(x[0], x[4], x[1], x[2]) for x in X], size, {**src, "part": "整字 clean_patch"}), d / "whole_bank.json")
        print("写", d / "ids_bank.json", (d / "ids_bank.json").stat().st_size, d / "whole_bank.json", (d / "whole_bank.json").stat().st_size)
