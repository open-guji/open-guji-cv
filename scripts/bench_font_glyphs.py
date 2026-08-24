"""字体字形 vs 刻本字形：分来源的匹配力实测。

回答一个 go/no-go 问题：**用开源字体渲染的字形，能不能匹配上刻本字形？**

做法：拿字形库里每个人工确认过的刻本 exemplar 当查询，分别只在一个字体
来源里检索（`GlyphDB.query(editions=[...])`），看正确字有没有排到第一、
分数多少、`verify_pair` 判什么。刻本来源自身做对照组（同版自查询应满分）。

输出每个来源一行：recall@1 / f1 分位数 / verdict 分布，以及「正确字排第一
时的 f1」与「错字排第一时的 f1」的重叠程度——后者才决定阈值能不能划出来。

    python scripts/bench_font_glyphs.py [--store glyph_store] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402


def pct(xs: list[float], q: float) -> float:
    return float(np.percentile(xs, q)) if xs else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="glyph_store")
    ap.add_argument("--json", default=None, help="结果写入 JSON")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    store = Path(args.store)

    db = GlyphDB(store / "glyphdb.sqlite")
    editions = [(r[0], r[1], r[2]) for r in db.conn.execute(
        """SELECT s.edition_tag, COALESCE(s.kind,'woodblock'),
                  COUNT(DISTINCT g.char)
           FROM sources s LEFT JOIN glyphs g ON g.edition_tag = s.edition_tag
           GROUP BY s.edition_tag ORDER BY 2, 1""")]
    print("库内来源：")
    for tag, kind, n in editions:
        print(f"  {tag:32s} kind={kind:10s} {n:6d} 字")

    # 查询集：刻本来源的每个 exemplar（人工确认过的真实字形）
    queries: list[tuple[str, str, np.ndarray]] = []
    for iid, char in db.conn.execute(
            """SELECT e.instance_id, g.char FROM exemplars e
               JOIN glyphs g ON g.glyph_id = e.glyph_id
               JOIN instances i ON i.instance_id = e.instance_id
               JOIN sources s ON s.source_id = i.source_id
               WHERE COALESCE(s.kind,'woodblock') = 'woodblock'
               ORDER BY e.instance_id"""):
        png = store / "patches" / f"{iid.replace(':', '_')}.png"
        if not png.exists():
            continue
        gray = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        queries.append((iid, char, normalize_patch(gray)))
    print(f"\n查询集：{len(queries)} 个刻本 exemplar，"
          f"{len(set(c for _, c, _ in queries))} 个字\n")

    report: dict[str, dict] = {}
    for tag, kind, n_chars in editions:
        hit1 = 0
        f1_correct: list[float] = []      # 正确字排第一时的 f1
        f1_wrong: list[float] = []        # 错字排第一时的 f1
        verdicts: Counter = Counter()
        rank_of_truth: list[int] = []
        n_eval = 0
        for iid, char, norm in queries:
            # 留一：自身实例必须在检索里排除，不能事后过滤（见 query 文档）
            hits = db.query(norm, editions=[tag], k=args.k, exclude=[iid])
            if not hits:
                continue
            n_eval += 1
            top = hits[0]
            verdicts[top.verdict] += 1
            if top.char == char:
                hit1 += 1
                f1_correct.append(top.f1)
            else:
                f1_wrong.append(top.f1)
            rank = next((i for i, h in enumerate(hits) if h.char == char), -1)
            rank_of_truth.append(rank)
        if not n_eval:
            continue
        in_topk = sum(1 for r in rank_of_truth if r >= 0)
        rec = {
            "kind": kind, "chars_in_edition": n_chars, "evaluated": n_eval,
            "recall@1": round(hit1 / n_eval, 4),
            f"recall@{args.k}": round(in_topk / n_eval, 4),
            "verdicts": dict(verdicts),
            "f1_correct": {
                "n": len(f1_correct), "p10": round(pct(f1_correct, 10), 4),
                "median": round(pct(f1_correct, 50), 4),
                "p90": round(pct(f1_correct, 90), 4)},
            "f1_wrong_top1": {
                "n": len(f1_wrong), "median": round(pct(f1_wrong, 50), 4),
                "p90": round(pct(f1_wrong, 90), 4)},
        }
        # 阈值可分性：正确命中的 f1 下十分位 vs 错误命中的 f1 上十分位
        if f1_correct and f1_wrong:
            rec["separable"] = bool(pct(f1_correct, 10) > pct(f1_wrong, 90))
            rec["margin"] = round(pct(f1_correct, 10) - pct(f1_wrong, 90), 4)
        report[tag] = rec
        print(f"[{tag}] kind={kind}")
        print(f"  recall@1 {rec['recall@1']:.3f}  "
              f"recall@{args.k} {rec[f'recall@{args.k}']:.3f}  "
              f"(n={n_eval})")
        print(f"  正确命中 f1: p10={rec['f1_correct']['p10']:.3f} "
              f"中位={rec['f1_correct']['median']:.3f} "
              f"p90={rec['f1_correct']['p90']:.3f} "
              f"(n={rec['f1_correct']['n']})")
        if f1_wrong:
            print(f"  错误命中 f1: 中位={rec['f1_wrong_top1']['median']:.3f} "
                  f"p90={rec['f1_wrong_top1']['p90']:.3f} "
                  f"(n={len(f1_wrong)})")
        print(f"  verdict: {dict(verdicts)}")
        if "margin" in rec:
            print(f"  可分性: {'是' if rec['separable'] else '否'} "
                  f"(margin={rec['margin']:+.3f})")
        print()

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
