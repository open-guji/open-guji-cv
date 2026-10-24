# -*- coding: utf-8 -*-
"""CV 产物 → guji-page → guji-format 一章（A2：`NNN.pages.json` 生成；F3，overview#398）。只读产物，不改现有导出。

一章一组文件：`NNN.lines.md`、`NNN.pages.json`（版框/列条带/字格坐标 + 锚点）、`NNN.proof.json`（method/review/
channel/cand）、`NNN.norm.json`、`NNN.zi.json`；给了 `--punct`/`--entity` 就按锚点重挂后一并写出，并报告
多少条靠锚点、多少条退到偏移、多少条两头都对不上。格式见 `doc/formats/format_merge_a1.md`。

    python scripts/export_guji_format.py --products <products 根> --book vol02 --chapter 002 \\
        --meta meta.json --out out/ [--pages 1-188] [--split-table 裁剪框表.json] \\
        [--punct 002.punct.json --entity 002.entity.json] [--only pages]

`--meta` 同 `export_guji_page.py`。`--only pages` 只写 pages.json（A2 的最小交付）。

`--format char-cord`（F4，overview#419）出 book-text 新形态：`NNN.char.json`（字，文本真源）、`NNN.cord.json`
（只存像素框）、`NNN.norm.json`（按格位记例外），见 `open_guji_cv/formats/guji_char_cord.py`。走法是先照旧在内存里
出 pages.json，再纯转换；写出前核 schema、cord↔char 格位与页列号，并核 char 生成的分行稿与同一次导出的
lines.md 逐字相同。`--keys cv|lines` 选格位口径（缺省 cv，照 spec 02）。缺省 `--format legacy` = 原来那组文件。

    python scripts/export_guji_format.py --products <products 根> --book vol02 --chapter 002 \\
        --meta meta.json --out out/ --format char-cord --text-version 0.1.0 [--keys cv]

`--text-version` 在 char-cord 下必填、没有缺省（GUJI-679）：首次出写 0.1.0，已是 0.1.x 的册写 book-text 上的现行版本
（以前缺省写 0.1.0，出补丁前得先手工改回线上版本，踩过）。

**图（GUJI-740）**：char-cord 下缺省读本册的图片格（排除名单理由 figure）与插图块（`figure_region` 事件），用到图就多出
`NNN.fig.json` 与 `fig/NNN/<图 id>.png|webp`（从 cord 该页 `image.sha256` 那张页图裁，先找 `--page-images`、工作区原图，
sha 对得上才用，再取 R2 页图 `blob.open-guji.com`；`--no-fetch` 不上网）。`--prev-fig <book-text 现行 NNN.fig.json>`
沿用旧图 id、保留重绘图（导出到已有图的册要给）。`--no-figures` 不读插图块事件与图片格说明（图片格本身由 Step7 产物
定，照出，说明写「图形符号」）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from convert_pages_to_char_cord import report as char_cord_report  # noqa: E402
from export_guji_page import page_meta  # noqa: E402

from open_guji_cv.formats import guji_char_cord as cc  # noqa: E402
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
    ap.add_argument("--only", choices=("pages",), default=None, help="只对 legacy")
    ap.add_argument("--format", choices=("legacy", "char-cord"), default="legacy",
                    help="legacy = lines.md＋pages/proof/norm/zi.json；char-cord = char.json＋cord.json＋norm.json")
    ap.add_argument("--keys", choices=cc.KEYS, default="cv", help="char-cord 的格位口径")
    ap.add_argument("--text-version", default=None,
                    help="char-cord 必填：char 的 version（首次 0.1.0；已有的册写 book-text 现行版本）")
    ap.add_argument("--no-figures", action="store_true", help="不读插图块事件与图片格说明（图片格照 Step7 产物出）")
    ap.add_argument("--prev-fig", default=None, help="book-text 现行的同章 fig.json：沿用图 id、保留重绘图")
    ap.add_argument("--page-images", default=None, help="页图目录（<页>.png），裁图先找这里")
    ap.add_argument("--no-fetch", action="store_true", help="裁图不取 R2 页图（只用本地）")
    a = ap.parse_args(argv)
    if a.format == "char-cord" and not a.text_version:
        ap.error("--format char-cord 要给 --text-version：首次出写 0.1.0，已有的册写 book-text 上的现行版本"
                 "（<册目录>/index.json 的 chapters[].text_version）")

    meta = json.loads(Path(a.meta).read_text(encoding="utf-8"))
    if a.split_table:
        rows = [r for r in json.loads(Path(a.split_table).read_text(encoding="utf-8")) if r["vol"] == a.book]
        meta.setdefault("defaults", {})["split_rows"] = rows
    products = Path(a.products) if a.products else None
    pages, bad = [], 0
    plist = _pages(a.pages, products, a.book)
    from open_guji_cv.feedback.vision import vision_pending_ids     # 看图判错待人审：导出记 review=pending
    pend = vision_pending_ids(a.book, plist, a.products)
    figure_alts, regions = {}, {}
    if a.format == "char-cord" and not a.no_figures:
        from open_guji_cv.feedback.figures import figure_cells, resolved_figure_regions
        figure_alts = figure_cells(a.book)
        regions = {pg: r for pg, r in resolved_figure_regions(a.book).items() if pg in set(plist)}
    for p in plist:
        try:
            page = export_page(a.products, a.book, p, page_meta(meta, p), pending_ids=pend, figure_alts=figure_alts)
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
    if a.format == "char-cord":
        conv = dict(zi=files[f"{a.chapter}.zi.json"], norm=files[f"{a.chapter}.norm.json"],
                    version=a.text_version, keys=a.keys, chapter=a.chapter)
        new, rep = cc.from_pages_json(pj, **conv, figure_regions=regions, prev_fig=load(a.prev_fig))
        fig = new.get(f"{a.chapter}.fig.json")
        if fig is not None:
            for e in cc.crop_figures(fig, new[f"{a.chapter}.cord.json"], _image_loader(a), a.out):
                print(f"   ✗ {e}")
        cc.write_files(new, a.out)
        st = cc.stats(new[f"{a.chapter}.char.json"], new[f"{a.chapter}.cord.json"])
        fr = rep["figures"]
        print(f"{a.book} 章 {a.chapter}（char-cord，keys={a.keys}）：{st['pages']} 页、{st['cells']} 格（有框 {st['boxed']}）、"
              f"阙文 {st['lacuna']}（其中带推测字 {st['guess_c']}）；没写进 cord 的 {rep['dropped']} → {a.out}")
        if fig is not None:
            print(f"   图：图片格 {fr['inline']}、插图块 {fr['block']}（占掉的格 {len(fr['dropped_cells'])}）、"
                  f"保留重绘 {fr['kept']} → {a.out}/fig/{a.chapter}/")
        base = cc.from_pages_json(pj, **conv)[0][f"{a.chapter}.char.json"] if regions else None
        bad += char_cord_report(new, md, roundtrip_char=base)
        return 1 if bad else 0
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


def _image_loader(a):
    """`(页, sha256) → PIL 图 | None`：`--page-images/<页>.png` → 工作区原图 → R2 页图；本地的 sha 对不上不用。"""
    import hashlib
    import io
    import urllib.request

    from PIL import Image

    def local(page: int) -> list[Path]:
        out = [Path(a.page_images) / f"{page}.png"] if a.page_images else []
        try:
            from open_guji_cv.core.book import load_book
            out.append(Path(load_book(a.book).raw_path(page)))
        except Exception:  # noqa: BLE001 — 没有工作区就只看别的来源
            pass
        return out

    def load(page: int, sha: str | None):
        for p in local(page):
            if p.exists():
                data = p.read_bytes()
                if not sha or hashlib.sha256(data).hexdigest() == sha:
                    return Image.open(io.BytesIO(data))
        if sha and not a.no_fetch:
            url = f"https://blob.open-guji.com/sha256/{sha[:2]}/{sha}.png"
            req = urllib.request.Request(url, headers={"User-Agent": "open-guji-cv/export-fig"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
            except OSError as e:
                print(f"   ✗ 取 R2 页图失败 p{page}：{e}")
                return None
            if hashlib.sha256(data).hexdigest() == sha:
                return Image.open(io.BytesIO(data))
        return None
    return load


if __name__ == "__main__":
    raise SystemExit(main())
