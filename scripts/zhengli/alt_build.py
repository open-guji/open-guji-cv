#!/usr/bin/env python3
"""相似字 `alt` 的字形雪碧图（以字找字，cv doc/research/人审找字-以字找字与异体族按图排序.md §10）。

来源：ai-team `team/整理/GUJI-557/alt_build.py`，2026-10-20 迁入 cv `scripts/zhengli/`（GUJI-652）。
迁入适配：`--cv-root` 改为可选，缺省用本仓根（本文件上两级），字体即本仓 `fonts/`；仍可显式给别的 cv 仓（兼容旧用法）；main() 加可选 argv 参数（便于测试）。
用途：给 pending.json 里每格相似字 `alt` 的每个字配一张字体字形图，拼成雪碧图并在 alt 项上标坐标。

`alt` 本身由 cv `guji audit alt` 在出待审单时算好（近似字的异体族按字块图排序），经
同目录 `pending_list.py --cards` 并进 pending.json；本脚本只给其中每个字配一张**字体字形图**，
网站上候选按钮就不靠读者电脑的字体（扩展区字常常显示不出来）。

读：pending.json（已带 alt，可已带 img／ex）。字体用 cv 仓 `fonts/`：I.Ming 优先（明体，近刻本），
I.Ming 没有的字用 Jigmo（覆盖到扩展 G）。两套都没有的字不出图，按钮照旧显示文字。
产出到 --out（与 sprite_build.py／ex_build.py 同一目录）：
  alt-<章号>.webp       96×96 网格、WebP q80、宽 ≤2048（每行 21 格），超行数拆 alt-<章号>-b.webp…
  assets.json          追加 alt 文件条目（rev 须与 pending.rev 一致，否则退出）
  pending.with-alt.json alt 每项加 g={s,x,y,w,h}（没图的字不加）
用法：
    python3 scripts/zhengli/alt_build.py --pending <pending.json> [--cv-root <open-guji-cv 根，缺省本仓>] --chapter 001 --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_build import COLS, TILE  # noqa: E402

MAX_ROWS = 150                      # 150×96=14400 < WebP 16383
FONTS = ("iming", "jigmo")
INK = 0.80                          # 字面占格的比例
#: 本仓根（scripts/zhengli/ 上两级）：--cv-root 的缺省值（GUJI-652 迁入后）。
CV_ROOT = Path(__file__).resolve().parents[2]


def glyph_tile(img) -> Image.Image:
    """cv 字体渲染（256² 灰度，白底黑字）→ 去白边、等比缩进 96² 格，四周留白。"""
    im = Image.fromarray(img).convert("L")
    bbox = Image.eval(im, lambda v: 255 - v).getbbox()
    if bbox:
        im = im.crop(bbox)
    s = TILE * INK / max(im.width, im.height)
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    t = Image.new("L", (TILE, TILE), 255)
    t.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
    return t


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pending", required=True, type=Path)
    ap.add_argument("--cv-root", type=Path, default=CV_ROOT, help="open-guji-cv 根目录（缺省本仓根）")
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    sys.path.insert(0, str(a.cv_root))
    from open_guji_cv.clustering.glyph_selfcheck import font_renderer

    pend = json.loads(a.pending.read_text(encoding="utf-8"))
    chars: list[str] = []
    for c in pend["cells"]:
        for x in c.get("alt") or ():
            if x["c"] not in chars:
                chars.append(x["c"])
    renderers = [r for r in (font_renderer(f) for f in FONTS) if r]
    if not renderers:
        sys.exit(f"cv 仓 fonts/ 下找不到 {FONTS} 字体")
    tiles: list[tuple[str, Image.Image]] = []
    miss = []
    for ch in chars:
        img = next((im for im in (r.render(ch) for r in renderers) if im is not None), None)
        if img is None:
            miss.append(ch)
            continue
        tiles.append((ch, glyph_tile(img)))

    pos: dict[str, dict] = {}
    files = []
    per_sheet = COLS * MAX_ROWS
    a.out.mkdir(parents=True, exist_ok=True)
    for si in range(0, len(tiles), per_sheet):
        part = tiles[si:si + per_sheet]
        name = f"alt-{a.chapter}.webp" if si == 0 else f"alt-{a.chapter}-{chr(ord('a') + si // per_sheet)}.webp"
        cols = min(COLS, len(part))
        sheet = Image.new("L", (cols * TILE, -(-len(part) // cols) * TILE), 255)
        for i, (ch, t) in enumerate(part):
            x, y = (i % cols) * TILE, (i // cols) * TILE
            sheet.paste(t, (x, y))
            pos[ch] = {"s": name, "x": x, "y": y, "w": TILE, "h": TILE}
        p = a.out / name
        sheet.save(p, "WEBP", quality=80)
        raw = p.read_bytes()
        files.append({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                      "w": sheet.width, "h": sheet.height})
    ap_path = a.out / "assets.json"
    if ap_path.is_file():
        man = json.loads(ap_path.read_text(encoding="utf-8"))
        if man["rev"] != pend["rev"]:
            sys.exit(f"assets.json rev={man['rev']} 与 pending.rev={pend['rev']} 不一致")
        keep = [f for f in man["files"] if not re.fullmatch(rf"alt-{re.escape(a.chapter)}(-[a-z])?\.webp", f["name"])]
        man["files"] = keep + files
        ap_path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cells = []
    n_cells = 0
    for c in pend["cells"]:
        if c.get("alt"):
            n_cells += 1
            # 两套字体都没有的字不出图，也去掉旧单上残留的 g（指向的格子在新图里已是别的字）
            c = dict(c, alt=[dict(x, g=pos[x["c"]]) if x["c"] in pos else {k: v for k, v in x.items() if k != "g"}
                             for x in c["alt"]])
        cells.append(c)
    (a.out / "pending.with-alt.json").write_text(json.dumps(dict(pend, cells=cells), ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    print(f"带 alt 的格 {n_cells}/{len(pend['cells'])}，相似字 {len(chars)}，出图 {len(tiles)}，"
          f"两套字体都没有 {len(miss)}：{''.join(miss[:40])}，字节 {sum(f['bytes'] for f in files)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
