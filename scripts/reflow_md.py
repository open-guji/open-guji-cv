# -*- coding: utf-8 -*-
"""Step9 结果整理 · 9.2' 文本版分段 + 标点：命令行入口。

只吃 9.1 分行 md（`render_guji_markdown.py` / `export_wikisource.py` 的 `<book>.md`），
不查产物。产物是 book-text 的 `original/` 版本目录（见 --out）：

    original/
      index.json          章目录（格式同其他版本）
      001.md              分段（+标点）后的阅读文本，页界用 `<!-- pN -->`
      001.lines.md        原始分行（9.1），逐列一行，`#第N页` 换成 `<!-- pN -->`
      report.json         分段统计、待复核点、标点失败块

    PYTHONIOENCODING=utf-8 PYTHONPATH=. venv/Scripts/python.exe scripts/reflow_md.py \\
        bxgb.md --profile diary --punct qwen --out <dir> \\
        --chapter 1:北行日錄上:3-38 --chapter 2:北行日錄下:39-56 \\
        --book-id 988g7gsqhd --title 北行日錄 --genre 宋人出使日記

`--punct none` 只分段不标点（不调 LLM）。LLM 缓存在 `<out>/.punct_cache/`（不提交）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.render.reflow_text import PAGE_MARK, PROFILES, Para, reflow  # noqa: E402

_MARK = re.compile(r"\x00p(\d+)\x00")


def _show(text: str) -> str:
    return _MARK.sub(lambda m: f"<!-- p{m.group(1)} -->", text)


def _split_pages(md: str, lo: int, hi: int) -> str:
    """取 md 里第 lo~hi 页（含），保持 `#第N页` 头。"""
    keep, on = [], False
    for ln in md.splitlines():
        m = re.match(r"^#第(\d+)页\s*$", ln)
        if m:
            on = lo <= int(m.group(1)) <= hi
        if on:
            keep.append(ln)
    return "\n".join(keep) + "\n"


def _raw_lines_md(md: str) -> str:
    return re.sub(r"^#第(\d+)页\s*$", lambda m: f"<!-- p{m.group(1)} -->", md, flags=re.M)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("md")
    ap.add_argument("--profile", default="default", choices=sorted(PROFILES))
    ap.add_argument("--punct", default="none", choices=["none", "qwen", "glm"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chapter", action="append", default=[], help="N:标题:起页-止页，可重复；缺省整份一章")
    ap.add_argument("--book-id", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--genre", default="古籍文字", help="给 LLM 的体裁提示，如「宋人出使日記」「四庫全書總目提要」")
    ap.add_argument("--hint", default="")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    md = Path(args.md).read_text(encoding="utf-8")
    pages_all = sorted({int(x) for x in re.findall(r"^#第(\d+)页", md, flags=re.M)})
    chapters: list[tuple[int, str, int, int]] = []
    for c in args.chapter:
        n, title, rng = c.split(":")
        lo, _, hi = rng.partition("-")
        chapters.append((int(n), title, int(lo), int(hi or lo)))
    if not chapters:
        chapters = [(1, args.title or "全文", pages_all[0], pages_all[-1])]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    client = None
    if args.punct != "none":
        from open_guji_cv.render.punct_llm import PunctClient
        client = PunctClient(args.punct, args.model, cache_dir=out / ".punct_cache")

    report: dict = {"profile": args.profile, "punct": args.punct,
                    "model": client.model if client else None, "chapters": []}
    index_chapters = []
    for n, title, lo, hi in chapters:
        sub = _split_pages(md, lo, hi)
        paras, stats = reflow(sub, args.profile)
        notes = [f"{x}" for p in paras for x in p.notes]
        fail_notes: list[str] = []
        if client:
            from open_guji_cv.render.punct_llm import punctuate_all
            res = punctuate_all([p.text for p in paras], client, workers=args.workers,
                                genre=args.genre, hint=args.hint)
            texts = [r.text for r in res]
            fail_notes = [x for r in res for x in r.notes]
            stats["punct_failed_paras"] = sum(1 for r in res if not r.ok)
            stats["punct_changed_chars"] = sum(r.changed_chars for r in res)
        else:
            texts = [p.text for p in paras]
        name = f"{n:03d}"
        (out / f"{name}.md").write_text("\n\n".join(_show(t) for t in texts) + "\n", encoding="utf-8")
        (out / f"{name}.lines.md").write_text(_raw_lines_md(sub), encoding="utf-8")
        index_chapters.append({"n": n, "file": name, "title": title, "has_json": False,
                               "lines_file": f"{name}.lines.md", "pages": f"{lo}-{hi}"})
        report["chapters"].append({"n": n, "title": title, "pages": [lo, hi], "stats": stats,
                                   "review_notes": notes, "punct_fail_notes": fail_notes})
        print(f"[{name}] {title} p{lo}-{hi}: {stats}")

    index = {"version_label": "開源古籍自校本（草稿）", "revision": "0.1.0",
             "book_id": args.book_id, "guji_markdown": "0.2.0", "chapters": index_chapters,
             "note": "由 open-guji-cv Step9 的 9.1 分行稿经 9.2' 文本版分段（+LLM 标点）而来；"
                     "草稿，未入 manifest。原始分行见各章 .lines.md。"}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写入 {out}")


if __name__ == "__main__":
    main()
