# -*- coding: utf-8 -*-
"""CV 产物 → guji-page v0.2（每字带坐标的页面文本）。只读产物，不改任何现有导出。

规范：doc/formats/guji_page_v0.2.md。一页一个 JSON；可顺带出 guji-markdown、IIIF 注释与 canvas、册级索引。

    python scripts/export_guji_page.py --products <products 根> --book vol03 --pages 3,107 \\
        --meta samples/meta.json --out out/ [--md] [--iiif] [--split-table 四庫合扫拆页-裁剪框.json] [--index]

`--split-table`：整理总管落盘的合扫拆页裁剪框表（overview `项目进展/新书整理/书/四庫合扫拆页-裁剪框.json`），
按 `--book` 取该册的行，工作区页号据此换成 canvas 页序（IA leaf + a–d），拆块页 canvas = 裁剪框。

`--meta`：CV 自己不知道的页级信息（Book ID、IIIF 册号、IA 原叶、拆页裁切区域、人工印章框），
格式见规范 §3.1 与 `doc/formats/samples/guji_page_v0/meta.json`。顶层 `defaults` 对所有页生效，
`pages["107"]` 按页覆盖（浅合并到 image / page 两块，marks 整体替换）。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.formats import guji_page as gp  # noqa: E402
from open_guji_cv.formats.guji_page_cv import export_page  # noqa: E402


def page_meta(meta: dict, page: int) -> dict:
    m = copy.deepcopy(meta.get("defaults", {}))
    over = meta.get("pages", {}).get(str(page), {})
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(m.get(k), dict):
            m[k].update(v)
        else:
            m[k] = v
    m.setdefault("page", {})
    m["page"].setdefault("index", page)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--products", default=None, help="产物根（含 <book>/<step>/）；缺省按 GUJI_PRODUCTS_DIR/工作区")
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", required=True, help="逗号分隔页号")
    ap.add_argument("--meta", required=True, help="页级元信息 JSON")
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", action="store_true", help="同时出 guji-markdown（.md）")
    ap.add_argument("--iiif", action="store_true", help="同时出 IIIF 注释（target = canvas.id#xywh=）与 canvas 骨架")
    ap.add_argument("--split-table", default=None, help="合扫拆页裁剪框表 JSON")
    ap.add_argument("--index", action="store_true", help="同时出册级 index.json（页 → book-text 章映射先留空）")
    a = ap.parse_args(argv)

    meta = json.loads(Path(a.meta).read_text(encoding="utf-8"))
    if a.split_table:
        rows = [r for r in json.loads(Path(a.split_table).read_text(encoding="utf-8")) if r["vol"] == a.book]
        meta.setdefault("defaults", {})["split_rows"] = rows
    done = []
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for p in [int(x) for x in a.pages.split(",") if x.strip()]:
        m = page_meta(meta, p)
        page = export_page(a.products, a.book, p, m)
        errs = gp.check(page) + [e for e in gp.validate_schema(page) if "未安装" not in e]
        stem = f"p{p:04d}"
        gp.dump(page, out / f"{stem}.guji-page.json")
        if a.md:
            (out / f"{stem}.md").write_text(gp.to_guji_markdown(page) + "\n", encoding="utf-8")
        if a.iiif:
            ann = gp.to_iiif_annotations(page)
            (out / f"{stem}.iiif-annotations.json").write_text(
                json.dumps(ann, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            (out / f"{stem}.iiif-canvas.json").write_text(
                json.dumps(gp.to_iiif_canvas(page), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        done.append(page)
        n_box = sum(1 for g in page["glyphs"] if g.get("box"))
        print(f"{a.book} p{p}: 字元 {len(page['text'])}，字框 {len(page['glyphs'])}（有框 {n_box}），"
              f"标记 {len(page['marks'])}，检查 {'通过' if not errs else '失败'}")
        for e in errs:
            print("   ✗", e)
        for w in page.get("warnings", []):
            print("   !", w)
        bad += bool(errs)
    if a.index and done:
        import hashlib
        files = {p["page"]["index"]: {"file": f"p{p['page']['index']:04d}.guji-page.json",
                                      "sha256": hashlib.sha256((out / f"p{p['page']['index']:04d}.guji-page.json")
                                                               .read_bytes()).hexdigest()} for p in done}
        (out / "index.json").write_text(json.dumps(gp.volume_index(done, files=files), ensure_ascii=False, indent=1)
                                        + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
