# -*- coding: utf-8 -*-
"""Step9 结果整理 · 坐标转字符位：命令行入口。

    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe \
        scripts/render_guji_markdown.py vol01 33 --out out.md
    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe \
        scripts/render_guji_markdown.py vol01 33 34 35

渲染逻辑在 `open_guji_cv/render/guji_markdown.py`（含设计依据与已知边界的
完整说明）——控制台路由 `console/routers/step9.py` 直接 import 同一份逻辑，
本文件只是命令行这一种调用形式的薄封装。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.errors import ProductMissing  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.render.approx import (APPROX_MODES, DEFAULT_APPROX_MODE,  # noqa: E402
                                       approx_marks, inline_ids_map, sidecar_rows, sidecar_tsv)
from open_guji_cv.render.guji_markdown import render_page  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("pages", nargs="+", type=int)
    ap.add_argument("--out", default=None, help="输出文件（缺省打印到 stdout）")
    ap.add_argument("--approx", choices=APPROX_MODES, default=DEFAULT_APPROX_MODE,
                    help="近似字（overview#276）：sidecar=正文照填、另出 <out>.approx.tsv（缺省）；"
                         "inline_ids=正文括注 字{ids=…}；off=都不出")
    args = ap.parse_args()
    marks = approx_marks(args.book) if args.approx != "off" else {}
    inline = inline_ids_map(marks) if args.approx == "inline_ids" else None

    store = ProductStore()
    parts: list[str] = []
    stale: list[str] = []
    for page in args.pages:
        parts.append(f"#第{page}页")
        try:
            parts.append(render_page(store, args.book, page, stale, approx_ids=inline))
        except ProductMissing as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)

    if stale:
        print(f"⚠ {len(stale)} 处 Step7 记录在 Step3 cells 里查不到对应格子"
              f"（Step3 局部重切后 Step7 没跟着重跑，见 render/guji_markdown.py "
              f"docstring）：{', '.join(stale)}", file=sys.stderr)
        print("这些字位按裸正文字兜底输出，可能把夹注/空白格拆错——"
              "先用 `python -m open_guji_cv status` 查这些页是否过期，"
              "重跑到 seed_admit 之后再信这份输出。", file=sys.stderr)

    text = "\n".join(parts) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"写入 {args.out}（{len(args.pages)} 页）")
    else:
        print(text, end="")
    rows = sidecar_rows(marks, args.pages) if args.approx == "sidecar" else []
    if rows:
        tsv = sidecar_tsv(rows)
        if args.out:
            side = Path(args.out).with_suffix(Path(args.out).suffix + ".approx.tsv")
            side.write_text(tsv, encoding="utf-8")
            print(f"近似字侧表 {side}（{len(rows)} 处）")
        else:
            print(f"── 近似字侧表（{len(rows)} 处）──\n{tsv}", end="", file=sys.stderr)


if __name__ == "__main__":
    main()
