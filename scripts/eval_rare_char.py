# -*- coding: utf-8 -*-
"""量 `rare-char` 集上的候选召回：现状 vs 加了字体模板之后。

KPI 是 **top-10 命中率**（人在候选里点得到），不是 top-1 准确率。
分层报：`in_candidates=False` 那档才是真难题——现状对它的召回按定义是 0。

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_rare_char.py [--k 10]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

DS = Path("../open-guji-dataset/rare-char")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(DS))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--paddle", action="store_true",
                    help="加 PP-OCRv5 一列（子进程 worker，见 candidates.PaddleOcrSource）")
    a = ap.parse_args()

    from open_guji_cv.clustering.font_candidates import book_charset, candidates
    from open_guji_cv.clustering.normalize import normalize_patch

    items = [json.loads(l) for l in
             (Path(a.dataset) / "items.jsonl").read_text(encoding="utf-8").splitlines()]
    if a.limit:
        items = items[:a.limit]
    # 字表：整理本用字 + 集里的参考答案（有些字整理本自己都没有，如 䙝 㕔）
    charset = book_charset(a.corpus, [i["expected"]["char"] for i in items])
    print(f"字表 {len(charset)} 字；样本 {len(items)} 条")

    paddle = None
    if a.paddle:
        from open_guji_cv.clustering.candidates import PaddleOcrSource
        paddle = PaddleOcrSource(topk=5)
        paddle._ensure()

    rows = []
    for it in items:
        exp = it["expected"]
        ref = exp["char"]
        cur = ([c for c, _ in it["input"]["db_candidates"]]
               + [c for c, _ in it["input"]["ocr_topk"]]
               + [c for c, _ in it["input"]["context_ranked"]])
        p = it["input"]["patch"]
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE) if p else None
        hits: list[str] = []
        if img is not None:
            norm = normalize_patch(img)
            hits = [h.char for h in candidates(norm, charset, k=a.k)]
        pd = []
        if paddle is not None and img is not None:
            pd = [c for c, _ in paddle.rec_topk(img)]
        rows.append({
            "id": it["id"], "ref": ref, "freq": exp["corpus_freq"],
            "hard": not exp["in_candidates"],
            "cur_hit": ref in cur[:a.k * 3],
            "font_hit": ref in hits,
            "font_rank": (hits.index(ref) + 1) if ref in hits else None,
            "font_top3": hits[:3],
            "paddle_top1": (pd[0] if pd else None),
            "paddle_hit": ref in pd,
            "union_hit": (ref in cur[:a.k * 3]) or (ref in hits) or (ref in pd),
        })

    def rate(sub, key):
        return (sum(1 for r in sub if r[key]) / len(sub)) if sub else 0.0

    hard = [r for r in rows if r["hard"]]
    easy = [r for r in rows if not r["hard"]]
    print(f"\n== top-{a.k} 命中率 ==")
    print(f"  全部 {len(rows)}：现状 {rate(rows,'cur_hit'):.1%}  "
          f"字体模板 {rate(rows,'font_hit'):.1%}  "
          f"两者并集 {sum(1 for r in rows if r['cur_hit'] or r['font_hit'])/len(rows):.1%}")
    if hard:
        print(f"  真难题 {len(hard)}（三路都没答案）：现状 {rate(hard,'cur_hit'):.1%}  "
              f"字体模板 **{rate(hard,'font_hit'):.1%}**")
    if easy:
        print(f"  稀有但候选里有 {len(easy)}：现状 {rate(easy,'cur_hit'):.1%}  "
              f"字体模板 {rate(easy,'font_hit'):.1%}")
    if paddle is not None:
        print(f"  PP-OCRv5 top1 {sum(1 for r in rows if r['paddle_top1']==r['ref'])/len(rows):.1%}  "
              f"top5 {rate(rows,'paddle_hit'):.1%}  三源并集 top-k {rate(rows,'union_hit'):.1%}"
              + (f"  真难题并集 {rate(hard,'union_hit'):.1%}" if hard else ""))
        paddle.close()
    ranks = [r["font_rank"] for r in rows if r["font_rank"]]
    if ranks:
        print(f"  字体命中时的名次：中位 {sorted(ranks)[len(ranks)//2]}，"
              f"top-1 {sum(1 for x in ranks if x == 1)}，top-3 {sum(1 for x in ranks if x <= 3)}")
    print("\n== 逐条 ==")
    for r in rows:
        mark = "✓" if r["font_hit"] else "×"
        print(f"  {mark} {r['id']:<20} {r['ref']} freq={r['freq']:<4} "
              f"{'难' if r['hard'] else '易'} 字体名次={r['font_rank']} "
              f"top3={''.join(r['font_top3'])}"
              + (f"  v5={r['paddle_top1'] or '∅'}{'✓' if r['paddle_hit'] else ''}" if paddle is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
