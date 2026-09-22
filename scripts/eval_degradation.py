# -*- coding: utf-8 -*-
"""固定退化协议（任务卡 2026-09-22 T5③）：同一批真刻例，加一组**固定**扰动，分因素报各路的稳定性。

    PYTHONIOENCODING=utf-8 python scripts/eval_degradation.py [--set oov|unseen] [--json out.json]

扰动集（每条一个因素，参数写死，别调）：
  clean / blur σ=0.8,1.5,2.5（高斯后重新二值） / erode 1px / dilate 1px /
  hline 2 条横向抹白（断墨） / vline 1 条竖向抹白 / edge 贴边 3px 残渣（界行/版框压边） /
  occl 10%,20%,30% 随机方块遮挡 / stamp 圆形钤印状遮挡（半径 12px 实心）。
报数：emb 对字体模板均值的 top-1 / top-10（字表 = 类表 ∪ 真刻例的字，类表外的字现渲染）、cls 头 top-1、
「结构 = 最近模板类的结构」的合体准确率（设计稿 §13 ④ 那条零训练路）。
模板均值优先复用 `cache/struct_probe/emb_*.npz`（probe_struct_heads.py 的缓存）；没有就现渲染。
真刻例来源：`cache/oov_bench`（类外）或 glyph_bench `unseen`（类内、无真刻例训练）。
这是评测不是测试；数据是 bundle，不进 git。
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SIZE = 64


def perturb_set(rng: np.random.RandomState):
    import cv2

    def blur(s):
        def f(x):
            g = cv2.GaussianBlur(x.astype(np.float32) * 255, (0, 0), s)
            return (g > 127).astype(np.uint8)
        return f

    def occl(frac):
        def f(x):
            y = x.copy(); side = int(round(np.sqrt(frac) * SIZE))
            ox, oy = rng.randint(0, SIZE - side + 1, 2); y[oy:oy + side, ox:ox + side] = 0
            return y
        return f

    def hline(x):
        y = x.copy()
        for _ in range(2):
            r = rng.randint(6, SIZE - 8); y[r:r + 2, :] = 0
        return y

    def vline(x):
        y = x.copy(); c = rng.randint(6, SIZE - 8); y[:, c:c + 2] = 0; return y

    def edge(x):
        y = x.copy(); side = rng.randint(0, 4); w = 3
        if side == 0: y[:w, :] = 1
        elif side == 1: y[-w:, :] = 1
        elif side == 2: y[:, :w] = 1
        else: y[:, -w:] = 1
        return y

    def stamp(x):
        y = x.copy(); cx, cy = rng.randint(12, SIZE - 12, 2)
        yy, xx = np.ogrid[:SIZE, :SIZE]; y[(xx - cx) ** 2 + (yy - cy) ** 2 <= 12 ** 2] = 1
        return y

    k = np.ones((2, 2), np.uint8)
    return [
        ("clean", lambda x: x),
        ("blur0.8", blur(0.8)), ("blur1.5", blur(1.5)), ("blur2.5", blur(2.5)),
        ("erode1", lambda x: cv2.erode(x, k)), ("dilate1", lambda x: cv2.dilate(x, k)),
        ("hline2", hline), ("vline1", vline), ("edge3px", edge),
        ("occl10", occl(0.10)), ("occl20", occl(0.20)), ("occl30", occl(0.30)),
        ("stamp", stamp),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="oov", choices=["oov", "unseen"])
    ap.add_argument("--json", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    import cv2
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    from open_guji_cv.clustering.ids_struct import SINGLE, structure_of
    from open_guji_cv.clustering.normalize import normalize_patch

    cnn = CnnCandidates(DEFAULT_CKPT)
    if not cnn.available:
        print("没有 checkpoint / torch", file=sys.stderr); return 2
    cnn._ensure(); classes = list(cnn._classes); cidx = {c: i for i, c in enumerate(classes)}

    # 模板均值
    cache = sorted(glob.glob("cache/struct_probe/emb_*.npz"))
    if cache:
        z = np.load(cache[-1], allow_pickle=True); fe, fc = z["font_emb"], z["font_chars"]
    else:
        from open_guji_cv.clustering.font_candidates import _font_files
        from open_guji_cv.clustering.synth import render_char
        xs, fc = [], []
        for f in _font_files():
            for ch in classes:
                try:
                    im = render_char(ch, f, size=SIZE)
                except Exception:
                    continue
                if im is not None and im.any():
                    xs.append(im.astype(np.uint8)); fc.append(ch)
        fe = np.concatenate([cnn.embed(xs[i:i + 256]) for i in range(0, len(xs), 256)]); fc = np.array(fc)
    # 真刻例
    imgs, gold = [], []
    if a.set == "oov":
        for l in Path("cache/oov_bench/items.jsonl").read_text(encoding="utf-8").splitlines():
            it = json.loads(l); im = cv2.imread(str(Path("cache/oov_bench") / it["png"].replace("\\", "/")), 0)
            if im is not None:
                imgs.append((im > 127).astype(np.uint8)); gold.append(it["char"])
    else:
        for l in Path("cache/glyph_bench/items.jsonl").read_text(encoding="utf-8").splitlines():
            it = json.loads(l)
            if it["split"] != "unseen":
                continue
            im = cv2.imread(it["png"].replace("\\", "/"), 0)
            if im is not None:
                imgs.append(normalize_patch(im).astype(np.uint8)); gold.append(it["char"])
    # 模板字表 = 类表 ∪ 真刻例的字（oov_bench 的字**全在类表外**，不补模板 emb@k 恒 0）；
    # 类表外的字现渲染字体取均值，与 `_emb_index` 同一口径（字体渲染均值）。
    extra_chars = sorted({g for g in gold if g not in cidx})
    if extra_chars:
        from open_guji_cv.clustering.font_candidates import _font_files
        from open_guji_cv.clustering.synth import render_char
        xs, xc = [], []
        for f in _font_files():
            for ch in extra_chars:
                try:
                    im = render_char(ch, f, size=SIZE)
                except Exception:
                    continue
                if im is not None and im.any():
                    xs.append(im.astype(np.uint8)); xc.append(ch)
        if xs:
            fe = np.concatenate([fe, np.concatenate([cnn.embed(xs[i:i + 256]) for i in range(0, len(xs), 256)])])
            fc = np.concatenate([np.asarray(fc), np.array(xc)])
    names = classes + extra_chars
    cidx = {c: i for i, c in enumerate(names)}
    M = np.zeros((len(names), 256), np.float32); n = np.zeros(len(names))
    for e, c in zip(fe, fc):
        if c in cidx:
            M[cidx[c]] += e; n[cidx[c]] += 1
    M /= np.maximum(n, 1)[:, None]; M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
    cls_struct = [structure_of(c).top for c in names]
    gi = np.array([cidx.get(g, -1) for g in gold])
    print(f"{a.set}: {len(imgs)} 条，模板字表 {len(names)}（类表 {len(classes)} + 补 {len(extra_chars)}）", flush=True)

    rng = np.random.RandomState(a.seed)
    rows = {}
    print(f"{'扰动':10s} emb@1  emb@10  cls@1  结构(最近类)")
    for name, fn in perturb_set(rng):
        rng_state = rng.get_state()
        xs = [fn(x) for x in imgs]
        E = np.concatenate([cnn.embed(xs[i:i + 256]) for i in range(0, len(xs), 256)])
        S = E @ M.T; top = np.argsort(-S, axis=1)[:, :10]
        cls_top = [r[0][0] if r else "" for r in cnn.topk_batch(xs, classes, k=1)]   # cls 头只认类表，oov 上恒 0 是应该的
        e1 = e10 = c1 = so = sn = 0; m = 0
        for j, g in enumerate(gold):
            if gi[j] >= 0:
                m += 1; e1 += int(top[j, 0] == gi[j]); e10 += int(gi[j] in top[j]); c1 += int(cls_top[j] == g)
            st = structure_of(g).top
            if st != SINGLE:
                sn += 1; so += int(cls_struct[top[j, 0]] == st)
        rows[name] = {"emb_top1": 100 * e1 / max(m, 1), "emb_top10": 100 * e10 / max(m, 1),
                      "cls_top1": 100 * c1 / max(m, 1), "struct_nn": 100 * so / max(sn, 1)}
        r = rows[name]
        print(f"{name:10s} {r['emb_top1']:5.1f}  {r['emb_top10']:6.1f}  {r['cls_top1']:5.1f}  {r['struct_nn']:5.1f}", flush=True)
        rng.set_state(rng_state)
    if a.json:
        Path(a.json).write_text(json.dumps({"set": a.set, "n": len(imgs), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
