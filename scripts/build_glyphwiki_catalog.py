# -*- coding: utf-8 -*-
"""建 GlyphWiki 变体形目录：dump → 「关联字 ∈ 字表、非别名」的字形 → kage 渲染 64² 二值图。

    PYTHONIOENCODING=utf-8 python scripts/build_glyphwiki_catalog.py \
        --dump <dump_newest_only.txt> --node-dir <装了 @kurgm/kage-engine 的目录> \
        [--charset unicode-cjk-ab | --charset corpus] [--out cache/glyphwiki/catalog_64.npz]

产物（**不进 git**，与 dump 一样是可再生的机器产物）：
- `<out>`：npz，`names`（GlyphWiki 名）/ `related`（关联字）/ `source`（前缀：zihai twedu dkw …/ IDS）
  / `imgs`（N×64×64 uint8 {0,1}，与 `synth.render_char` 同口径：96 画布占 0.8 → 64）；
- `<out>.tsv`：同一份目录的可读版。
`cnn_candidates._gw_index` 读它当**第六套模板档**（每字取 max，不混进字体均值——混进去
oov top-1 掉 9.6，见设计稿 §13 ⑤）。来源、许可、数字见 `unencoded_char_sources_survey.md` §2.1。

为什么是这几类前缀：dump 里 215 万字形大半是日本古字书/戸籍/工业字体等与刻本无关的；
留的是中华字海 zihai、教育部字典 twedu、大漢和 dkw、平安字书 hdic、IDS 命名 u2ffX-、
CDP 部件 cdp、康熙 kx、大藏經 sat/cbeta、IRG 工作集 irg、戸籍 koseki、GT gt、toki。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KEEP = ("IDS", "zihai", "twedu", "dkw", "hdic", "toki", "cdp", "koseki", "cbeta", "gt", "irg", "kx", "sat",
        "utc", "uk", "extd", "extf")
ALIAS = re.compile(r"^99:0:0:0:0:200:200:(u[0-9a-f]{4,5}(?:-[a-z0-9]+)?)$")

RENDER_JS = r"""
const { Kage, Polygons } = require('@kurgm/kage-engine'); const fs = require('fs');
const inp = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')); const kage = new Kage();
for (const [n, d] of Object.entries(inp.glyphs)) kage.kBuhin.push(n, d);
const out = {}; let bad = 0;
for (const t of inp.targets) { const p = new Polygons(); try { kage.makeGlyph(p, t); } catch (e) { bad++; continue; }
  out[t] = p.array.map(q => q.array.map(r => [r.x, r.y])); }
fs.writeFileSync(process.argv[3], JSON.stringify(out)); console.log('rendered', Object.keys(out).length, 'bad', bad);
"""


def source_of(name: str) -> str | None:
    if re.match(r"^u2ff[0-9a-f]-", name):
        return "IDS"
    m = re.match(r"([a-z]+)", name)
    p = m.group(1) if m else None
    return p if p in KEEP else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--node-dir", required=True)
    ap.add_argument("--charset", default="unicode-cjk-ab", help="base_charset 名，或 corpus（整理本字表）")
    ap.add_argument("--corpus", default=None, help="--charset corpus 时的语料文件；缺省走刻本链 DEFAULT_CORPUS")
    ap.add_argument("--out", default="cache/glyphwiki/catalog_64.npz")
    a = ap.parse_args()
    import cv2
    from PIL import Image, ImageDraw

    if a.charset == "corpus":
        from open_guji_cv.clustering.font_candidates import book_charset
        from open_guji_cv.clustering.rare_panel import DEFAULT_CORPUS
        cs = set(book_charset(a.corpus or DEFAULT_CORPUS))
    else:
        from open_guji_cv.clustering.charset_spec import base_charset
        cs = set(base_charset(a.charset))
    t0 = time.time()
    db: dict[str, str] = {}
    rows: list[tuple[str, str, str]] = []
    with open(a.dump, encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3 or parts[0] in ("name", "") or parts[0].startswith("-"):
                continue
            name, rel, data = parts
            db[name] = data
            m = re.match(r"^u([0-9a-f]{4,5})$", rel)
            if not m or ALIAS.match(data):
                continue
            ch = chr(int(m.group(1), 16))
            if ch not in cs:
                continue
            src = source_of(name)
            if src:
                rows.append((name, ch, src))
    print(f"dump {len(db)} 条；字表 {len(cs)}；目录 {len(rows)} 形  {time.time()-t0:.0f}s", flush=True)

    need: dict[str, str] = {}
    stack = [r[0] for r in rows]
    while stack:
        n = stack.pop(); base = n if n in db else n.split("@")[0]
        if base not in db or base in need:
            continue
        need[base] = db[base]
        for part in db[base].split("$"):
            fs = part.split(":")
            if fs and fs[0] == "99" and len(fs) >= 8:
                stack.append(fs[7])
    nd = Path(a.node_dir)
    (nd / "_gw_render.cjs").write_text(RENDER_JS, encoding="utf-8")
    (nd / "_gw_in.json").write_text(json.dumps({"targets": [r[0] for r in rows], "glyphs": need}, ensure_ascii=False),
                                    encoding="utf-8")
    subprocess.run(["node", "_gw_render.cjs", "_gw_in.json", "_gw_out.json"], cwd=nd, check=True)
    polys = json.loads((nd / "_gw_out.json").read_text(encoding="utf-8"))
    print(f"kage 渲染 {len(polys)} 形（闭包 {len(need)} 部件） {time.time()-t0:.0f}s", flush=True)

    C = 96; s = C * 0.8 / 200.0; off = (C - 200 * s) / 2
    meta = {r[0]: r for r in rows}
    names, rel, src, imgs = [], [], [], []
    for n, pl in polys.items():
        im = Image.new("L", (C, C), 255); dr = ImageDraw.Draw(im)
        for poly in pl:
            pts = [(x * s + off, y * s + off) for x, y in poly]
            if len(pts) >= 3:
                dr.polygon(pts, fill=0)
        b = (np.asarray(im) < 128).astype(np.uint8)
        g = (cv2.resize(b * 255, (64, 64), interpolation=cv2.INTER_AREA) > 127).astype(np.uint8)
        if not g.any():
            continue
        names.append(n); rel.append(meta[n][1]); src.append(meta[n][2]); imgs.append(g)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, names=np.array(names), related=np.array(rel), source=np.array(src),
                        imgs=np.stack(imgs).astype(np.uint8), charset=a.charset)
    with open(str(out) + ".tsv", "w", encoding="utf-8") as f:
        f.write(f"# GlyphWiki 变体形目录 charset={a.charset} n={len(names)} built={time.strftime('%Y-%m-%d')}\n"
                "gw_name\trelated\tsource\n")
        for n, r, sname in zip(names, rel, src):
            f.write(f"{n}\t{r}\t{sname}\n")
    print(f"→ {out}  {len(names)} 形 / {len(set(rel))} 字  {out.stat().st_size/1e6:.1f} MB  {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
