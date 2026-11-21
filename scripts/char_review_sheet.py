# -*- coding: utf-8 -*-
"""按字归并的快速审阅表（史记文渊阁冷启动，GUJI-750）。

借来的殿本字形库首位字 ＝ 整理本（页钉位对出来的）字的格，是两路独立证据一致的「快速录入备选」。
按字归并：每个字一行，贴若干张字块图，人一眼看整行对不对；对的整字点 OK，混进去的错格点图标红。
出一份自包含 HTML（字块缩成小 JPEG 内嵌），审完导出 JSON：`ok` 字表、`bad` 格号、`check` 存疑字。

用法：char_review_sheet.py <工作区> <册> <out.html> [--per-char 14]
只读产物（glyph_match / align_ref / seed_admit）和 cache/<册>/char_patch，不写库。"""
from __future__ import annotations

import argparse
import base64
import collections
import glob
import io
import json
import re
from pathlib import Path

from PIL import Image

#: 己已巳、日曰：同形字，只能按文意判（runbook S10），人看字形图判不了，快审页不收。
AMBIGUOUS = "己已巳日曰"

TEMPLATE = Path(__file__).with_name("char_review_sheet.tpl.html")
GRID_TEMPLATE = Path(__file__).with_name("char_review_grid.tpl.html")


def load(prod: Path):
    gm, ar, sa = {}, {}, {}
    for f in glob.glob(str(prod / "glyph_match/p*.json")):
        for c in json.load(open(f, encoding="utf-8"))["glyph_match"]["columns"]:
            for r in c["chars"]:
                gm[r["id"]] = r
    for f in glob.glob(str(prod / "align_ref/p*.json")):
        d = json.load(open(f, encoding="utf-8"))["align_ref"]
        for c in d["chars"]:
            if c["align_op"] in ("equal", "replace"):
                ar[c["id"]] = c["align_char"]
        for c in d.get("coord", []):
            if c.get("ref_char"):
                ar.setdefault(c["id"], c["ref_char"])
    for f in glob.glob(str(prod / "seed_admit/p*.json")):
        for c in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
            for x in c["chars"]:
                sa[x["id"]] = x
    return gm, ar, sa


def patch_name(cid: str) -> str:
    _b, page, col, slot = cid.split(":")
    m = re.fullmatch(r"(-?\d+)([ab]?)", slot)
    return f"p{int(page):04d}c{int(col):02d}s{m.group(1)}{m.group(2)}.png"


def thumb(path: Path, h: int = 52) -> str:
    im = Image.open(path).convert("L")
    w = max(8, round(im.width * h / im.height))
    im = im.resize((min(w, 90), h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=55)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def pick(ids: list[str], k: int) -> list[str]:
    key = lambda i: tuple(int(x) for x in re.findall(r"\d+", i))
    ids = sorted(ids, key=key)
    if len(ids) <= k:
        return ids
    return [ids[round(i * (len(ids) - 1) / (k - 1))] for i in range(k)]


def grid_mode(a, groups, gm, patches) -> None:
    """一页 N 格、一图一字：每字挑像素匹配度（glyph_match 首位 cov）最高的 `--per-char` 格，
    污渍、半截字块 cov 低，自然排在外面。按字频排，同字相邻。"""
    tiles = []
    for ch, ids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        best = sorted(ids, key=lambda i: -float(gm[i].get("cov") or 0))[:a.per_char]
        for i in sorted(best, key=lambda i: tuple(int(x) for x in re.findall(r"\d+", i))):
            p = patches / patch_name(i)
            if p.exists():
                tiles.append([i, ch, round(float(gm[i].get("cov") or 0), 3), thumb(p, 72), len(ids)])
    data = {"book": a.book, "per_page": a.grid, "n_chars": len(groups),
            "n_cells": sum(len(v) for v in groups.values()), "tiles": tiles}
    html = GRID_TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"{len(tiles)} 格（{len(groups)} 字，共 {data['n_cells']} 格可验）→ {a.out}（{Path(a.out).stat().st_size / 1e6:.1f} MB）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("book")
    ap.add_argument("out")
    ap.add_argument("--per-char", type=int, default=14)
    ap.add_argument("--grid", type=int, default=0,
                    help="每页 N 格、一图一字、默认全对（只点不对的）；每字挑 --per-char 个像素匹配度最高的格")
    ap.add_argument("--keep-ambiguous", action="store_true",
                    help="不跳过靠字形无法判的字（%s）；缺省跳过，这些字要按文意判，不放进快审页" % AMBIGUOUS)
    ap.add_argument("--unadmitted", action="store_true",
                    help="只出还没放行、但整理本有对应字的格（按整理本的字分组），用于第二轮")
    a = ap.parse_args()
    ws = Path(a.ws)
    gm, ar, sa = load(ws / "products" / a.book)
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for i, r in gm.items():
        top = (r.get("candidates") or [[None]])[0][0]
        if not a.keep_ambiguous and any(c and c in AMBIGUOUS for c in (top, ar.get(i))):
            continue
        if a.unadmitted:
            if ar.get(i) and not sa.get(i, {}).get("admit"):
                groups[ar[i]].append(i)
        elif top and ar.get(i) == top:
            groups[top].append(i)
    patches = ws / "cache" / a.book / "char_patch"
    if a.grid:
        return grid_mode(a, groups, gm, patches)
    rows = []
    for ch, ids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        shown = []
        for i in pick(ids, a.per_char):
            p = patches / patch_name(i)
            if p.exists():
                shown.append([i, thumb(p)])
        if shown:
            auto = sum(1 for i in ids if sa.get(i, {}).get("admit"))
            rows.append({"ch": ch, "n": len(ids), "auto": auto, "cells": shown})
    data = {"book": a.book, "n_cells": sum(r["n"] for r in rows), "rows": rows}
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"{len(rows)} 字、{data['n_cells']} 格 → {a.out}（{Path(a.out).stat().st_size / 1e6:.1f} MB）")


if __name__ == "__main__":
    main()
