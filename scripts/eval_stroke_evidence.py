# -*- coding: utf-8 -*-
"""量 5b 笔画证据（`font.stroke_evidence`）开关前后的候选名次：同一批字块走 `rare_for_batch` 两遍（关／开），
按层（全部／oov／unseen）报首位、前 5、前 k 命中，和首位改对、改错的格数。

    python scripts/eval_stroke_evidence.py --samples <dataset>/char-clustering/samples/004-siku-v2-human \\
        --patches <数据目录>/output/glyph_store/patches [--book vol01 --corpus <语料>] [--weight rrf:4 emb:0.1] [-k 10]

字块用字形库里同一实例的原灰度字块（`<实例号里的 : 换成 _ 或 ~>.png`），不是样本目录里的 64 像素归一图：
笔画检测要原图。不给 --book 时走缺省字表（基集＋阶梯）、两路融合，没有库字体域和真刻例原型；
给了 --book 时照这册的 `font` 配置走，但真刻例原型强制关（样本格自己就在库里，开着等于看答案）。
己已巳、日曰 折叠。只读，不写任何产物。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_fold import fold  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--patches", required=True)
    ap.add_argument("--book")
    ap.add_argument("--corpus")
    ap.add_argument("--weight", nargs="+", default=["rrf:4"], help="模式:权重，可给多个，如 rrf:4 emb:0.1")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out")
    a = ap.parse_args()

    from open_guji_cv.clustering.rare_panel import rare_for_batch
    rare = [json.loads(ln) for ln in (Path(a.samples) / "rare.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows, imgs = [], []
    for it in rare:
        p = next((q for q in (Path(a.patches) / (it["id"].replace(":", s) + ".png") for s in "_~") if q.is_file()), None)
        im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p else None
        if im is not None:
            rows.append(it)
            imgs.append(im)
    if a.limit:
        rows, imgs = rows[:a.limit], imgs[:a.limit]
    print(f"{Path(a.samples).name}：{len(rare)} 格，有原字块 {len(rows)} 格；book={a.book} k={a.k}", flush=True)

    def run(stroke):
        out = []
        for i in range(0, len(imgs), 128):
            out += rare_for_batch(imgs[i:i + 128], a.k, a.corpus, a.book, real_proto=(False, ()), stroke=stroke)
        return [[h["char"] for h in hits] for hits in out]

    def rank(tops):
        r = []
        for it, top in zip(rows, tops):
            g = fold(it["char"])
            pos = [j for j, c in enumerate(top) if fold(c) == g]
            r.append(pos[0] + 1 if pos else 10 ** 9)
        return np.array(r)

    layers = {"全部": np.ones(len(rows), bool),
              "oov": np.array(["oov" in it["strata"] for it in rows]),
              "unseen": np.array(["unseen" in it["strata"] for it in rows])}
    fmt = lambda r: "／".join("%.1f" % (100 * (r <= n).mean()) for n in (1, 5, a.k))  # noqa: E731
    base = run(None)
    r0 = rank(base)
    res = {"n": len(rows), "off": {k: fmt(r0[m]) for k, m in layers.items()}}
    for k, m in layers.items():
        print(f"  关        {k}（{int(m.sum())}） 首位／前5／前{a.k} {fmt(r0[m])}", flush=True)
    for w in a.weight:
        mode, wv = w.split(":")
        tops = run((True, float(wv), mode))
        r1 = rank(tops)
        same_set = sum(set(x) == set(y) for x, y in zip(base, tops))
        for k, m in layers.items():
            fx, br = int(((r0 > 1) & (r1 == 1) & m).sum()), int(((r0 == 1) & (r1 > 1) & m).sum())
            print(f"  开 {w:<8} {k}（{int(m.sum())}） 首位／前5／前{a.k} {fmt(r1[m])}  首位改对 {fx} 改错 {br}", flush=True)
            res[f"on_{w}_{k}"] = {"hit": fmt(r1[m]), "fixed": fx, "broken": br}
        print(f"           候选集合不变的格 {same_set}/{len(rows)}", flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
