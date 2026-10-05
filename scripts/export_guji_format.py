# -*- coding: utf-8 -*-
"""CV 产物 → guji-page → guji-format 一章（A2：`NNN.pages.json` 生成；F3，overview#398）。只读产物，不改现有导出。

一章一组文件：`NNN.lines.md`、`NNN.pages.json`（版框/列条带/字格坐标 + 锚点）、`NNN.proof.json`（method/review/
channel/cand）、`NNN.norm.json`、`NNN.zi.json`；给了 `--punct`/`--entity` 就按锚点重挂后一并写出，并报告
多少条靠锚点、多少条退到偏移、多少条两头都对不上。格式见 `doc/formats/format_merge_a1.md`。

    python scripts/export_guji_format.py --products <products 根> --book vol02 --chapter 002 \\
        --meta meta.json --out out/ [--pages 1-188] [--split-table 裁剪框表.json] \\
        [--punct 002.punct.json --entity 002.entity.json] [--only pages]

`--meta` 同 `export_guji_page.py`。`--only pages` 只写 pages.json（A2 的最小交付）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from export_guji_page import page_meta  # noqa: E402
from open_guji_cv.formats import guji_format as gf  # noqa: E402
from open_guji_cv.formats import guji_page as gp  # noqa: E402
from open_guji_cv.formats.guji_page_cv import export_page  # noqa: E402


def _pages(spec: str | None, products: Path | None, book: str) -> list[int]:
    if not spec:
        if products is None:
            raise SystemExit("不给 --products 时要给 --pages")
        return sorted(int(p.stem[1:]) for p in (products / book / "seed_admit").glob("p*.json"))
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        elif part.strip():
            out.append(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--products", default=None)
    ap.add_argument("--book", required=True)
    ap.add_argument("--chapter", required=True, help="book-text 章号 NNN，如 002")
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default=None, help="如 1-188 或 3,4,7；缺省 = 产物里有 seed_admit 的全部页")
    ap.add_argument("--split-table", default=None)
    ap.add_argument("--punct", default=None)
    ap.add_argument("--entity", default=None)
    ap.add_argument("--only", choices=("pages",), default=None)
    a = ap.parse_args(argv)

    meta = json.loads(Path(a.meta).read_text(encoding="utf-8"))
    if a.split_table:
        rows = [r for r in json.loads(Path(a.split_table).read_text(encoding="utf-8")) if r["vol"] == a.book]
        meta.setdefault("defaults", {})["split_rows"] = rows
    products = Path(a.products) if a.products else None
    pages, bad = [], 0
    for p in _pages(a.pages, products, a.book):
        try:
            page = export_page(a.products, a.book, p, page_meta(meta, p))
        except Exception as e:  # noqa: BLE001 — 缺产物的页报出来、不中断整章
            print(f"   ✗ p{p}: {type(e).__name__}: {e}")
            bad += 1
            continue
        errs = gp.check(page)
        if errs:
            print(f"   ✗ p{p} 检查不过：{errs[:3]}")
            bad += 1
        pages.append(page)
    load = (lambda x: json.loads(Path(x).read_text(encoding="utf-8")) if x else None)
    files = gf.to_guji_format(pages, chapter=a.chapter, punct=load(a.punct), entity=load(a.entity))
    pj, md = files[f"{a.chapter}.pages.json"], files[f"{a.chapter}.lines.md"]
    back, _ = gf.from_guji_format(files)                      # 往返自检：读回来必须等于去 ext 的原页
    if back != [gp.strip_ext(p) for p in pages]:
        print("   ✗ 往返自检不过：guji-format 读回的 guji-page 与原页不同")
        bad += 1
    if a.only == "pages":
        files = {k: v for k, v in files.items() if k.endswith(".pages.json")}
    gf.write_files(files, a.out)
    n_cells = sum(len(p["cells"]) for p in pj["pages"])
    n_box = sum(1 for p in pj["pages"] for c in p["cells"] if c.get("box"))
    print(f"{a.book} 章 {a.chapter}：{len(pages)} 页、{pj['n_chars']} 字元、{n_cells} 格（有框 {n_box}）→ {a.out}")
    idx = gf.anchor_index(pj)
    for name, path in (("punct", a.punct), ("entity", a.entity)):
        if path:
            _, rep = gf.reattach(load(path), idx, md)
            print(f"   {name}：按锚点 {rep['by_anchor']}、退到偏移 {rep['by_offset']}、对不上 {len(rep['lost'])}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
