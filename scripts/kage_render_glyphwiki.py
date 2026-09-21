# -*- coding: utf-8 -*-
"""把 GlyphWiki 的 KAGE 字形离线渲染成位图——给「Unicode 未收字」造模板的原型。

    python scripts/kage_render_glyphwiki.py --dump <dump_newest_only.txt> --node-dir <dir> \
        --out <outdir> --size 256 zihai-032338 u2ff8-u5e7f-u542c twedu-a03839-002 ...

- `<dump>`：https://glyphwiki.org/dump.tar.gz 解开的 `dump_newest_only.txt`（约 310 MB，
  215 万条；许可：自由使用/可商用/无需署名，见包内 LICENSE.txt）。
- `<node-dir>`：跑过 `npm install @kurgm/kage-engine`（MIT）的目录；本脚本把一段 JS 写进去执行。
- 输出：每个名字一张 `<name>.png`（白底黑字、只缩不放的 200 单位画布 → `--size`），另有
  `manifest.tsv`（name / related 关联字 / 多边形数）。

流程：Python 读 dump 建索引 → 递归收部件闭包（`99:` 引用行第 8 栏是部件名，`@版本` 后缀去掉）
→ node 里 kage-engine 出多边形 → PIL 填充。实测（2026-09-21 云端）：2,155,000 条建索引 7.4 s，
9 个字（闭包 42 部件）渲染 14 ms。这是 `unencoded_char_sources_survey.md` §5 层 1 的第一块砖，
**不是管线的一部分**，不进 `python -m open_guji_cv`。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RENDER_JS = r"""
const { Kage, Polygons } = require('@kurgm/kage-engine');
const fs = require('fs');
const inp = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const kage = new Kage();
for (const [n, d] of Object.entries(inp.glyphs)) kage.kBuhin.push(n, d);
const out = {};
for (const t of inp.targets) {
  const polys = new Polygons();
  try { kage.makeGlyph(polys, t); } catch (e) { out[t] = null; continue; }
  out[t] = polys.array.map(p => p.array.map(q => [q.x, q.y]));
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""


def load_dump(path: Path) -> dict[str, tuple[str, str]]:
    db: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3 or parts[0] in ("name", "") or parts[0].startswith("-"):
                continue
            db[parts[0]] = (parts[1], parts[2])
    return db


def closure(db: dict[str, tuple[str, str]], targets: list[str]) -> dict[str, str]:
    need: dict[str, str] = {}
    stack = list(targets)
    while stack:
        n = stack.pop()
        base = n if n in db else n.split("@")[0]
        if base not in db or base in need:
            continue
        need[base] = db[base][1]
        for part in db[base][1].split("$"):
            f = part.split(":")
            if f and f[0] == "99" and len(f) >= 8:
                stack.append(f[7])
    return need


def rasterize(polys: list[list[list[float]]], size: int):
    from PIL import Image, ImageDraw
    im = Image.new("L", (size, size), 255)
    dr = ImageDraw.Draw(im)
    for poly in polys:
        pts = [(x * size / 200.0, y * size / 200.0) for x, y in poly]
        if len(pts) >= 3:
            dr.polygon(pts, fill=0)
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="GlyphWiki 字形名，如 zihai-032338 / u2ff8-u5e7f-u542c")
    ap.add_argument("--dump", required=True)
    ap.add_argument("--node-dir", required=True, help="装了 @kurgm/kage-engine 的目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=256)
    a = ap.parse_args()

    db = load_dump(Path(a.dump))
    targets = [n for n in a.names if n in db]
    missing = [n for n in a.names if n not in db]
    if missing:
        print(f"dump 里没有：{missing}", file=sys.stderr)
    if not targets:
        return 1
    node_dir = Path(a.node_dir)
    (node_dir / "_kage_render.cjs").write_text(RENDER_JS, encoding="utf-8")
    inp = node_dir / "_kage_in.json"
    outp = node_dir / "_kage_out.json"
    inp.write_text(json.dumps({"targets": targets, "glyphs": closure(db, targets)}, ensure_ascii=False),
                   encoding="utf-8")
    subprocess.run(["node", "_kage_render.cjs", str(inp), str(outp)], cwd=node_dir, check=True)
    polys = json.loads(outp.read_text(encoding="utf-8"))

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in targets:
        p = polys.get(n)
        if not p:
            rows.append((n, db[n][0], 0))
            continue
        rasterize(p, a.size).save(out / f"{n}.png")
        rows.append((n, db[n][0], len(p)))
    (out / "manifest.tsv").write_text(
        "name\trelated\tpolygons\n" + "".join(f"{n}\t{r}\t{k}\n" for n, r, k in rows), encoding="utf-8")
    print(f"→ {out}  {sum(1 for r in rows if r[2])} / {len(rows)} 渲染成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
