# -*- coding: utf-8 -*-
"""T4 变体形模板闸检查：GW 开关前后，`cache/glyph_bench`（unseen 严格）与
`cache/oov_bench` 两条闸线不掉。

跟 `eval_oov.py`/`eval_zero_shot_fusion.py` 量的是同一个「emb」候选源，但直接走
`CnnCandidates.emb_topk_batch(gw_enabled=…)`——`eval_zero_shot_fusion.py` 的
RRF 融合是自己手写的矩阵乘法，没接 `_gw_index`（GW 只在 `emb_topk_batch` 里的
max 融合生效），这里用生产同一条代码路径量，不是另起一套口径。

    python scripts/eval_t4_gates.py [--charset unicode-cjk-ab]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GLYPH_BENCH = Path("cache/glyph_bench")
OOV_BENCH = Path("cache/oov_bench")


def _score(cnn, imgs, G, cs, k, gw_enabled, label) -> dict:
    cnn._gw_cs = None
    emb = cnn.emb_topk_batch(imgs, cs, k=k, gw_enabled=gw_enabled)
    n = len(G)
    t1 = sum(1 for r, g in zip(emb, G) if r and r[0][0] == g)
    t5 = sum(1 for r, g in zip(emb, G) if g in [c for c, _ in r[:5]])
    t10 = sum(1 for r, g in zip(emb, G) if g in [c for c, _ in r[:k]])
    print(f"  [{label}] n={n}  top1={t1/n*100:5.1f}%  top5={t5/n*100:5.1f}%  top10={t10/n*100:5.1f}%")
    return {"n": n, "top1": t1 / n * 100, "top5": t5 / n * 100, "top10": t10 / n * 100}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--charset", default="unicode-cjk-ab", help="oov_bench 候选字表")
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    from open_guji_cv.clustering.font_candidates import book_charset
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.steps.align_ref import DEFAULT_CORPUS

    cnn = CnnCandidates(a.ckpt or str(DEFAULT_CKPT))
    cnn._ensure()

    out: dict = {}

    # ── unseen（严格，只认同一码位）：cache/glyph_bench split==unseen ──
    items = [json.loads(l) for l in (GLYPH_BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    items = [i for i in items if i["split"] == "unseen"]
    imgs, G = [], []
    for it in items:
        img = cv2.imread(str(it["png"]).replace("\\", "/"), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        imgs.append(normalize_patch(img))
        G.append(it["char"])
    cs_corpus = tuple(book_charset(DEFAULT_CORPUS))
    print(f"unseen（严格）n={len(imgs)} / {len(set(G))} 字种；字表 {len(cs_corpus)} 字")
    out["unseen_off"] = _score(cnn, imgs, G, cs_corpus, a.k, False, "gw 关（基线）")
    out["unseen_on"] = _score(cnn, imgs, G, cs_corpus, a.k, True, "gw 开")

    # ── oov_bench ──
    items = [json.loads(l) for l in (OOV_BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    imgs, G = [], []
    for it in items:
        img = cv2.imread(str(OOV_BENCH / it["png"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        imgs.append((img > 127).astype(np.uint8))
        G.append(it["char"])
    cs_big = base_charset(a.charset)
    print(f"\noov_bench n={len(imgs)} / {len(set(G))} 字种；字表 {a.charset} {len(cs_big)} 字")
    out["oov_off"] = _score(cnn, imgs, G, cs_big, a.k, False, "gw 关（基线）")
    out["oov_on"] = _score(cnn, imgs, G, cs_big, a.k, True, "gw 开")

    print("\n闸线（任务书）：unseen 严格 top-10 ≥ 97.0，oov top-1 ≥ 74.5 / top-10 ≥ 91.7")
    print(f"  unseen 开 top-10 = {out['unseen_on']['top10']:.1f}  {'过' if out['unseen_on']['top10'] >= 97.0 else '不过'}")
    print(f"  oov    开 top-1  = {out['oov_on']['top1']:.1f}  {'过' if out['oov_on']['top1'] >= 74.5 else '不过'}")
    print(f"  oov    开 top-10 = {out['oov_on']['top10']:.1f}  {'过' if out['oov_on']['top10'] >= 91.7 else '不过'}")

    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n写入 {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
