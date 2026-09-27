# -*- coding: utf-8 -*-
"""Step9 结果整理 · 一键导出维基文库 `Page:` 页 wikitext。

    # 从产物出 9.1 md，再转 wikitext（最常用）
    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/bin/python scripts/export_wikisource.py bxgb -w <工作区>
    # 只转一份已有的（可能手改过的）9.1 md，不碰产物
    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/bin/python scripts/export_wikisource.py bxgb --md 某.md

产物落 `<工作区>/reports/<book>/wikisource/`（`--md` 模式缺省落 md 同目录）：
`<book>.md`（9.1 全书逐列稿，只在产物模式写）、`pNNN.wiki`（逐页，贴进编辑框「页面主体」）、
`all.wiki`（带目标页名的总览）、`notes.txt`（仍待人裁 / 阙文的字位，只在产物模式写）。
页眉页脚与校对等级在维基文库编辑界面里单独填，不在文件里。

记号约定（一列一行、版心出空行）见 `open_guji_cv/render/wikisource.py`。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.render.wikisource import convert  # noqa: E402

# 扫描页 → 维基文库 Page 名。
BOOKS = {
    "bxgb": {
        "pages": (3, 56),
        "wiki_page": lambda p: (f"Page:NLC403-312001066864-15647 北行日錄 卷一.pdf/{p}" if p <= 38
                                else f"Page:NLC403-312001066864-15646 北行日錄 卷二.pdf/{p - 38}"),
    },
}


def _render_md(book: str, pages: list[int]) -> tuple[str, list[str]]:
    """产物 → 9.1 md（与 `render_guji_markdown.py` 同一份逻辑），顺带列出待人裁/阙文字位。"""
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.render.guji_markdown import render_page
    from open_guji_cv.report.slots import page_slots

    store = ProductStore()
    parts: list[str] = []
    notes: list[str] = []
    stale: list[str] = []
    for p in pages:
        parts += [f"#第{p}页", render_page(store, book, p, stale, keep_empty_cols=True)]
        for s in page_slots(store, book, p):
            if not s.is_text:
                continue
            if s.unreadable or s.defect:
                notes.append(f"{s.id}\t" + (f"原刻残，照人给的字录「{s.guess}」" if s.guess
                                            else "阙文/原刻残 → □"))
            elif not s.admit:
                notes.append(f"{s.id}\t待人裁，暂出「{s.reading or s.char}」")
    notes += [f"{x}\tStep3/Step7 对不上（页过期？先 guji status）" for x in stale]
    return "\n".join(parts) + "\n", notes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book", choices=sorted(BOOKS))
    ap.add_argument("--md", default=None, help="直接转这份 9.1 md，不从产物生成")
    ap.add_argument("--pages", default=None, help="产物模式的页范围，如 3-56；缺省本书全部正文页")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("-w", "--workspace", default=None, help="工作区（产物模式必填）")
    args = ap.parse_args()
    cfg = BOOKS[args.book]

    notes: list[str] | None = None
    if args.md:
        md_path = Path(args.md)
        md = md_path.read_text(encoding="utf-8")
        out = Path(args.out) if args.out else md_path.parent
    else:
        if not args.workspace:
            ap.error("产物模式要 -w 工作区（不读 GUJI_WORKSPACE 兜底，理由同 guji pipeline）")
        import os
        os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).resolve())
        from open_guji_cv.core.workspace import reports_root
        lo, hi = cfg["pages"]
        if args.pages:
            a, _, b = args.pages.partition("-")
            lo, hi = int(a), int(b or a)
        md, notes = _render_md(args.book, list(range(lo, hi + 1)))
        out = Path(args.out) if args.out else reports_root() / args.book / "wikisource"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.book}.md").write_text(md, encoding="utf-8")

    out.mkdir(parents=True, exist_ok=True)
    pages = convert(md)
    combined = []
    for po in pages:
        (out / f"p{po.page:03d}.wiki").write_text(po.wikitext + "\n", encoding="utf-8")
        combined.append(f"<!-- ===== 掃描頁 {po.page} → {cfg['wiki_page'](po.page)} ===== -->\n"
                        f"{po.wikitext}\n")
    (out / "all.wiki").write_text("\n".join(combined), encoding="utf-8")
    msg = f"写入 {out}（{len(pages)} 页）"
    if notes is not None:
        (out / "notes.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
        msg += f"；{len(notes)} 条留意项见 notes.txt"
    print(msg)


if __name__ == "__main__":
    main()
