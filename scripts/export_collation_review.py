"""导出对勘复审页：我的定字 × 整理本的差异，逐条可改判、可打印 PDF。

    PYTHONPATH=. python scripts/export_collation_review.py output/vol01
    PYTHONPATH=. python scripts/export_collation_review.py output/vol01 \
        --kinds substitution,variant --out /tmp/collate.html

裁决沿用 GUJI-SEED-EVENT，页面上改完后把记录贴回，照旧用
``guji-cv seed-ingest`` 回收——不另立第二套协议。

「维持原判」不发事件（队列里本来就是那个字），只在页面上标记已看过；
故复审一轮下来记录里只会有真正改动的条目。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description="对勘复审页导出")
    ap.add_argument("book_out_dir", help="书输出目录 output/<book>/")
    ap.add_argument("--queue", default=None,
                    help="队列路径（缺省 <book>/phase9_seed/queue.jsonl）")
    ap.add_argument("--kinds", default=None,
                    help="只出这些类（逗号分隔：substitution,variant,"
                         "insertion,deletion；缺省全部）")
    ap.add_argument("--variants", default=None, help="异体表路径")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--out", default=None, help="输出 HTML（缺省写队列同目录）")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO))
    from open_guji_cv.clustering.review.collation_export import (
        KIND_LABELS, KIND_ORDER, build_collation_batch, render_collation_html)

    book_dir = Path(args.book_out_dir)
    queue = Path(args.queue) if args.queue \
        else book_dir / "phase9_seed" / "queue.jsonl"
    kinds = tuple(k.strip() for k in args.kinds.split(",")) if args.kinds \
        else KIND_ORDER
    bad = [k for k in kinds if k not in KIND_ORDER]
    if bad:
        raise SystemExit(f"未知类别 {bad}，可用：{', '.join(KIND_ORDER)}")

    batch = build_collation_batch(book_dir, queue, kinds=kinds,
                                  variants=args.variants, limit=args.limit)
    out = Path(args.out) if args.out else queue.parent / "collation_review.html"
    out.write_text(render_collation_html(batch), encoding="utf-8")

    c = batch["counts"]
    print(f"{batch['book']}：差异 {batch['total_diff']} 条，"
          f"一致 {batch['n_same']} 条（锚定页 "
          f"{'、'.join(batch['anchored_pages'])}）")
    for k in KIND_ORDER:
        if c.get(k):
            mark = "" if k in kinds else "（本次未出）"
            print(f"  {KIND_LABELS[k]:<4} {c[k]:>3}{mark}")
    print(f"HTML：{out}（{out.stat().st_size // 1024} KB，含 "
          f"{len(batch['entries'])} 张卡）")


if __name__ == "__main__":
    main()
