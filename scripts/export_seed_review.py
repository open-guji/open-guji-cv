"""导出「种子审查」单页 HTML（glyph_db_first_design.md §3.5 页面侧）。

    python scripts/export_seed_review.py output/vol02 \\
        --queue output/vol02/phase9_seed/queue.jsonl --page 4 --out review.html

<book> 是书输出目录（output/<book>/，phase4_chars 在其下）。--queue 缺省取
<book>/phase9_seed/queue.jsonl；--page 缺省取推进指针所在页（progress.json，
否则页号最小的待审页）；--out 缺省写到队列同目录 <batch_id>.html。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.review.seed_export import (build_seed_batch,
                                                        render_seed_html)


def main() -> None:
    ap = argparse.ArgumentParser(description="种子审查页面导出")
    ap.add_argument("book", help="书输出目录 output/<book>/")
    ap.add_argument("--queue", default=None,
                    help="队列路径（缺省 <book>/phase9_seed/queue.jsonl）")
    ap.add_argument("--page", default=None,
                    help="页号（缺省取推进指针所在页）")
    ap.add_argument("--out", default=None,
                    help="输出 HTML 路径（缺省写到队列同目录）")
    ap.add_argument("--limit", type=int, default=200,
                    help="单页最多导出条数（默认 200）")
    args = ap.parse_args()

    book_dir = Path(args.book)
    queue = Path(args.queue) if args.queue else \
        book_dir / "phase9_seed" / "queue.jsonl"

    try:
        batch = build_seed_batch(book_dir, queue, page=args.page,
                                 limit=args.limit)
    except (FileNotFoundError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    out = (Path(args.out) if args.out
           else queue.parent / f'{batch["batch_id"]}.html')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_seed_html(batch), encoding="utf-8")

    n = len(batch["entries"])
    print(f'已导出 {batch["book"]} 第 {batch["page"]} 页：'
          f'{n} 条待审（本页 {batch["page_done"]}/{batch["page_total"]} 已裁决，'
          f'全书 {batch["book_done"]}/{batch["book_total"]}）')
    print(f"HTML：{out}")
    if batch.get("pages_pending"):
        rest = "、".join(f'{p["page"]}({p["n"]})'
                         for p in batch["pages_pending"][:10])
        print(f"尚有待审页：{rest}")


if __name__ == "__main__":
    main()
