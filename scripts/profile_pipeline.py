# -*- coding: utf-8 -*-
"""管线性能剖析：分阶段计时 + 单页热点函数排名。

    # 单页热点（找瓶颈在哪个函数）
    PYTHONPATH=. python scripts/profile_pipeline.py hotspots output/vol01 --page 4
    # 阶段计时汇总（读 run 日志里的秒数 + 折算每页/每字耗时）
    PYTHONPATH=. python scripts/profile_pipeline.py summary --log /tmp/rerun_main.log

## 为什么单独做这个

全书重跑一次要十几分钟，光看总时长说明不了问题——同样是十分钟，可能是
「每页都均匀慢」也可能是「几页卡死拖平均」。所以两个视角都要：`summary`
给阶段/每页折算（横向比谁贵），`hotspots` 用 cProfile 跑**一页**给函数级
排名（纵向看这页的时间花在哪几行）。

跑 hotspots 时机器最好是闲的——与全书重跑抢核会把数字污染掉。
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def cmd_hotspots(args) -> None:
    """单页 cProfile。走与 CLI 同一条路（run_book + name_filter），
    免得 profile 出来的热点跟真跑的不是一回事。"""
    book_dir = Path(args.book_out_dir)
    pages = {args.page} if args.page else None
    if args.step == "chars":
        from open_guji_cv.clustering.extractor import CharExtractor
        runner = CharExtractor()
    else:
        from open_guji_cv.clustering.grid_segment import GridSegmenter
        from open_guji_cv.profile import BookProfile
        cpl, ncols = args.chars_per_line, None
        pf = Path(args.book_out_dir).parent.parent / "profile.json"
        pf2 = book_dir / "profile.json"
        for cand in (pf2, pf):
            if cand.exists():
                prof = BookProfile.load(cand)
                cpl = cpl or prof.chars_per_line
                ncols = prof.lines_per_page
                break
        runner = GridSegmenter(cpl, n_cols=ncols or None)

    pr = cProfile.Profile()
    t0 = time.time()
    pr.enable()
    meta = runner.run_book(book_dir, name_filter=pages)
    pr.disable()
    wall = time.time() - t0
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(args.top)
    print(f"=== {args.step} 页={args.page or '全书'}：墙钟 {wall:.1f}s "
          f"stats={meta.get('stats')} ===")
    for line in s.getvalue().splitlines():
        if re.match(r"\s+\d", line) or "ncalls" in line:
            print(line)


STEP_RE = re.compile(r"\[(\w+)\]\s+(\w+):\s+(\d+)s")


def cmd_summary(args) -> None:
    rows = []
    for line in Path(args.log).read_text(encoding="utf-8").splitlines():
        m = STEP_RE.search(line)
        if m:
            rows.append({"book": m.group(1), "step": m.group(2),
                         "sec": int(m.group(3))})
    if not rows:
        print("日志里没找到 [book] step: Ns 形式的计时行")
        return
    # 每页/每字折算
    for r in rows:
        meta = Path(args.output) / r["book"] / "phase4_chars" / "meta.json"
        pages = chars = None
        if meta.exists():
            st = json.loads(meta.read_text(encoding="utf-8")).get("stats", {})
            pages, chars = st.get("pages"), st.get("chars")
        r["pages"], r["chars"] = pages, chars
    print(f"{'册':>7} {'阶段':>8} {'秒':>6} {'页':>5} {'ms/页':>7} {'字':>7} {'ms/字':>7}")
    for r in sorted(rows, key=lambda x: -x["sec"]):
        pp = f"{r['sec']*1000/r['pages']:.0f}" if r["pages"] else "-"
        pc = f"{r['sec']*1000/r['chars']:.1f}" if r["chars"] else "-"
        print(f"{r['book']:>7} {r['step']:>8} {r['sec']:>6} "
              f"{r['pages'] or '-':>5} {pp:>7} {r['chars'] or '-':>7} {pc:>7}")
    print(f"\n合计 {sum(r['sec'] for r in rows)}s"
          f"（两册并行时墙钟约为最慢那册之和，见 rerun 总耗时）")


def main() -> None:
    ap = argparse.ArgumentParser(description="管线性能剖析")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hotspots", help="单页 cProfile 热点排名")
    h.add_argument("book_out_dir")
    h.add_argument("--step", default="segment", choices=["segment", "chars"])
    h.add_argument("--page", help="只跑这一页（缺省全书，很慢）")
    h.add_argument("--chars-per-line", type=int, default=21)
    h.add_argument("--top", type=int, default=25)
    h.set_defaults(fn=cmd_hotspots)
    s = sub.add_parser("summary", help="阶段计时 + 每页/每字折算")
    s.add_argument("--log", default="/tmp/rerun_main.log")
    s.add_argument("--output", default="output")
    s.set_defaults(fn=cmd_summary)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
