# -*- coding: utf-8 -*-
"""`seen_test` 单原型协议（R2/T11 的验收协议之一，`zero_shot_ccr_survey.md` §五.A）：

每类真刻例只留 1 个当模板（与字体均值 max 融合），用同类剩下的样本当查询，
对照纯字体模板——预期 emb 单源在这个协议下明显逼近分类头（`cls`），
证明「人裁一次之后，第二次出现就该稳稳排第一」这条直觉成立。

这是一个独立的小型验证协议，**不是**生产接线（生产接线是 `cnn_candidates.py`
里 `REAL_PROTO_ENABLED` 那一套 k<=3 聚类 + `glyph_store` 读取 + 留一法，见
`emb_topk_batch`）；这里为了协议干净，直接从 `glyph_bench` 里按类拆一个
模板/查询集，不经过 `glyph_store`。

    python scripts/eval_seen_test_single_proto.py --model models/glyph_cnn_r5/best.pt
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

BENCH = Path("cache/glyph_bench")


def main() -> int:
    ap = argparse.ArgumentParser()
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT
    ap.add_argument("--model", default=str(DEFAULT_CKPT))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--min-per-class", type=int, default=2,
                    help="类内至少这么多条才参与（1 个当模板，其余当查询）")
    ap.add_argument("--charset", default="unicode-cjk-ab",
                    help="候选字表——**不能**只用 seen_test 出现的类当字表：那样候选池只有"
                         "几百个字，字体模板闭卷都能对着 99%%+，测不出真刻例原型的增益。"
                         "字表越大，越接近生僻字候选的真实开卷场景")
    a = ap.parse_args()

    from open_guji_cv.clustering.cnn_candidates import CnnCandidates
    from open_guji_cv.clustering.normalize import normalize_patch

    items = [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    items = [i for i in items if i["split"] == "seen_test"]
    by_char: dict[str, list] = {}
    for it in items:
        by_char.setdefault(it["char"], []).append(it)
    rng = random.Random(a.seed)

    from open_guji_cv.clustering.charset_spec import base_charset

    cnn = CnnCandidates(a.model)
    cnn._ensure()
    classes = set(cnn._classes)
    cs = base_charset(a.charset)   # 大字表——候选池要难，见 --charset 的说明

    def _load(it):
        p = Path(str(it["png"]).replace("\\", "/"))
        im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if im is None:
            return None
        return normalize_patch(im)

    proto_ims, proto_chars, query_items = [], [], []
    for ch, lst in by_char.items():
        if len(lst) < a.min_per_class:
            continue
        lst = sorted(lst, key=lambda it: it["id"])
        rng.shuffle(lst)
        head, rest = lst[0], lst[1:]
        proto_ims.append(head); proto_chars.append(ch)
        query_items.extend(rest)
    print(f"参与类数 {len(proto_chars)}（seen_test 共 {len(by_char)} 类）；"
          f"查询样本 {len(query_items)} 条")

    proto_norms = [x for x in (_load(it) for it in proto_ims) if x is not None]
    proto_vecs = cnn.embed(proto_norms)
    proto_pos = {c: i for i, c in enumerate(proto_chars)}

    font_mat, font_names = cnn._emb_index(cs)
    font_pos = {c: i for i, c in enumerate(font_names)}

    q_norms, q_chars = [], []
    for it in query_items:
        n = _load(it)
        if n is None:
            continue
        q_norms.append(n); q_chars.append(it["char"])
    Q = cnn.embed(q_norms)   # (N, 256)

    sims_font = font_mat @ Q.T                      # (n_font_chars, N)
    sims_real = proto_vecs @ Q.T                    # (n_proto_chars, N)

    def _topk(col_font, col_real, k):
        best: dict[str, float] = {}
        for i, c in enumerate(font_names):
            best[c] = float(col_font[i])
        for i, c in enumerate(proto_chars):
            v = float(col_real[i])
            if v > best.get(c, -2.0):
                best[c] = v
        return [c for c, _ in sorted(best.items(), key=lambda kv: -kv[1])[:k]]

    def _topk_font_only(col_font, k):
        order = np.argsort(-col_font)[:k]
        return [font_names[int(i)] for i in order]

    stat = {"font_only": [0, 0, 0], "font_plus_real": [0, 0, 0], "cls_ref": [0, 0, 0]}
    cls_topk = cnn.topk_batch(q_norms, cs, k=a.k)
    for j, g in enumerate(q_chars):
        fo = _topk_font_only(sims_font[:, j], a.k)
        fr = _topk(sims_font[:, j], sims_real[:, j], a.k)
        co = [c for c, _ in cls_topk[j]]
        for name, order in (("font_only", fo), ("font_plus_real", fr), ("cls_ref", co)):
            stat[name][0] += order and order[0] == g
            stat[name][1] += g in order[:5]
            stat[name][2] += g in order[:a.k]

    n = len(q_chars)
    print(f"\n{'源':<16} {'top-1':>8} {'top-5':>8} {'top-10':>8}")
    for name in ("font_only", "font_plus_real", "cls_ref"):
        t1, t5, t10 = stat[name]
        print(f'{name:<16} {t1/n*100:7.1f}% {t5/n*100:7.1f}% {t10/n*100:7.1f}%')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
