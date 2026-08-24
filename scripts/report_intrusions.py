"""版面线侵入全书扫描 → 回流上游（G2 行列识别 / G3 字符网格）的证据报告。

    PYTHONPATH=. python scripts/report_intrusions.py output/vol01 [--out x.json]

## 为什么要按列/按位置聚集，而不是只报总数

单个图块带线可能是扫描噪声，**整列每格都带线**只可能是切窗定位偏了。
进库审查里最刺眼的一条就是这个：46 条「仅定字·不入库」有 15 条挤在
第 7 页第 6 列（整列吃进界行），32 条 not_a_char 有 30 条落在列尾
（网格越过末字撞上版框）。所以本报告的主表是**列级聚集**与**位置分布**
——这两个才是上游能直接照着修的信号，总数只是背景。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
COL_HOT = 0.5      # 一列里带线格占比 ≥ 此值 → 整列系统性偏移


def main() -> None:
    ap = argparse.ArgumentParser(description="版面线侵入扫描")
    ap.add_argument("book_out_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None, help="只扫前 N 个图块（调试）")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO))
    from open_guji_cv.clustering.crop_quality import detect_intrusion
    from open_guji_cv.clustering.extractor import load_index

    book_dir = Path(args.book_out_dir)
    root = book_dir / "phase4_chars"
    recs = [r for r in load_index(root) if r.cell_type == "char"]
    if args.limit:
        recs = recs[:args.limit]

    col_slots: dict[tuple[str, int], list] = defaultdict(list)
    for r in recs:
        col_slots[(r.page, r.col)].append(r)
    col_max = {k: max(x.idx for x in v) for k, v in col_slots.items()}

    codes = Counter()
    pos_ct: dict[str, Counter] = defaultdict(Counter)
    hits: dict[tuple[str, int], int] = Counter()
    per_instance: list[dict] = []
    n = 0
    for r in recs:
        g = cv2.imread(str(root / r.patch_path), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        n += 1
        codes_here = detect_intrusion(g)
        if not codes_here:
            continue
        m = col_max[(r.page, r.col)]
        pos = "列首" if r.idx == 0 else ("列尾" if r.idx >= m - 1 else "列中")
        for c in codes_here:
            codes[c] += 1
            pos_ct[c][pos] += 1
        hits[(r.page, r.col)] += 1
        per_instance.append({"instance_id": r.id, "page": r.page, "col": r.col,
                             "idx": r.idx, "pos": pos, "codes": codes_here})

    hot_cols = []
    for k, cnt in hits.items():
        total = len(col_slots[k])
        if total and cnt / total >= COL_HOT:
            hot_cols.append({"page": k[0], "col": k[1], "hit": cnt,
                             "slots": total, "rate": round(cnt / total, 3)})
    hot_cols.sort(key=lambda d: -d["rate"])

    report = {
        "book": book_dir.name,
        "n_scanned": n,
        "n_hit": len(per_instance),
        "hit_rate": round(len(per_instance) / n, 4) if n else 0,
        "by_code": dict(codes),
        "by_code_position": {k: dict(v) for k, v in pos_ct.items()},
        "hot_columns": hot_cols,
        "n_hot_columns": len(hot_cols),
        "instances": per_instance,
    }
    dest = Path(args.out) if args.out else book_dir / "phase4_chars" / "intrusions.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    print(f"扫描 {n} 个图块，命中 {len(per_instance)}（{report['hit_rate']:.1%}）")
    print("\n按码：")
    for c, v in codes.most_common():
        print(f"  {c:<18} {v:>5}   位置 {dict(pos_ct[c])}")
    print(f"\n整列系统性偏移（带线格占比 ≥ {COL_HOT:.0%}）：{len(hot_cols)} 列")
    for d in hot_cols[:15]:
        print(f"  第{d['page']}页第{d['col']}列  {d['hit']}/{d['slots']} = {d['rate']:.0%}")
    print(f"\n→ {dest}")


if __name__ == "__main__":
    main()
