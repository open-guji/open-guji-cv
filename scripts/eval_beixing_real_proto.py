# -*- coding: utf-8 -*-
"""北行 383 条用户裁决当真刻例多原型档（R2/T11）的额外靶——任务书「有就报」，
不是闸的一部分（闸是 unseen 严格 / oov_bench，见 `eval_oov.py` / `eval_zero_shot_fusion.py`）。

留一法：这 383 条字位自己的物理格摘除，不让它们自证自己（`_real_index` 的
`exclude_ids`，按 `match._cell_parts` 同册同页同列、格号相差 <=2 摘）。

    GUJI_WORKSPACE=<guji-workspace>/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一 \
      python scripts/eval_beixing_real_proto.py \
      --real-proto-store store:<同上路径>/output/glyph_store
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="bxgb")
    ap.add_argument("--ckpt", default="models/glyph_cnn_r5/best.pt")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--real-proto-store", action="append", default=[],
                    help="真刻例来源 store:<glyph_store 目录>，可重复")
    a = ap.parse_args()

    ws_str = os.environ.get("GUJI_WORKSPACE", "")
    ws = Path(ws_str)
    # `Path("").exists()` 是 True（解析成 cwd）——没设变量时不能拿它当"存在"判断。
    if not ws_str or not ws.exists():
        print("没设 GUJI_WORKSPACE（或路径不存在）——这条靶子拿不到北行的用户裁决，跳过。"
              "这是任务书里的『有就报』附加靶，不是闸的一部分。")
        return 0

    import open_guji_cv.clustering.cnn_candidates as _cc
    from open_guji_cv.clustering.cnn_candidates import CnnCandidates
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.rare_panel import _book_norm_stroke, book_charsets, rare_patch
    from open_guji_cv.eval.round_check import load_verdicts
    from open_guji_cv.steps.align_ref import book_corpus

    cc = CnnCandidates(a.ckpt)
    cc._ensure()
    classes = set(cc._classes)

    gold = load_verdicts(a.book, ws)
    cs_base, _cs_esc, spec = book_charsets(a.book, book_corpus(a.book))
    ns = _book_norm_stroke(a.book)
    imgs, G, ids = [], [], []
    for key in sorted(gold):
        p, c, s = key.split(":")[1:]
        im = rare_patch(a.book, int(p), int(c), int(s))
        if im is None:
            continue
        imgs.append(normalize_patch(im, stroke_width=ns))
        G.append(gold[key])
        ids.append(f"{p}:{c}:{s}")
    print(f"字位 {len(imgs)}（类外 {sum(1 for g in G if g not in classes)}）")
    exclude_ids = frozenset(ids)

    def _run(label: str, enabled: bool) -> None:
        _cc.REAL_PROTO_ENABLED = enabled
        if enabled:
            _cc.REAL_PROTO_SPECS = tuple(a.real_proto_store)
        cc._real_cs = None
        emb = cc.emb_topk_batch(imgs, cs_base, k=a.k,
                                 real_exclude_ids=exclude_ids if enabled else frozenset())
        stat = {"类外": [0, 0, 0], "类内": [0, 0, 0]}
        for r, g in zip(emb, G):
            order = [c for c, _ in r]
            st = "类内" if g in classes else "类外"
            stat[st][0] += 1
            stat[st][1] += g in order[:1]
            stat[st][2] += g in order[:a.k]
        tot = [stat["类外"][i] + stat["类内"][i] for i in range(3)]
        print(f"[{label}] "
              f"类外 n={stat['类外'][0]:3d} top1={stat['类外'][1]/max(stat['类外'][0],1):5.1%} "
              f"top10={stat['类外'][2]/max(stat['类外'][0],1):5.1%}  "
              f"类内 n={stat['类内'][0]:3d} top1={stat['类内'][1]/max(stat['类内'][0],1):5.1%} "
              f"top10={stat['类内'][2]/max(stat['类内'][0],1):5.1%}  "
              f"全体 top1={tot[1]/tot[0]:5.1%} top10={tot[2]/tot[0]:5.1%}")

    _run("real-proto 关（基线）", False)
    if a.real_proto_store:
        _run("real-proto 开", True)
    else:
        print("没给 --real-proto-store，只报基线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
