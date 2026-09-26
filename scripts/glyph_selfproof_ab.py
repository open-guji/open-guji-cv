# -*- coding: utf-8 -*-
"""「摘掉自证」的单变量对照：同一份 Step1–4 产物，Step5-a 只差 `exclude_self`，比 Step7 放行（字形库 10）。

    PYTHONPATH=. python scripts/glyph_selfproof_ab.py <book> --a <产物目录A> --b <产物目录B> \
        --db <glyph.db> [--pages 4-60,63-88] [--out 报告.json] [--sheet 联系表.png] [--sample 20]

A = `{"glyph_match": {"exclude_self": false}}`（改前：格一进库就自己配自己），B = 缺省 True（改后）。
两个目录的 Step1–4 必须是同一份（B 从 A 复制），否则差里掺了切分的变化——脚本会逐页比 char_index 的 sha 报出来。

报的东西：
- 自动放行率（分母 = seed_admit 里的全部字位，含命中排除名单的；另报不含排除的口径）；
- 按放行通道拆（A 的通道 → B 的去向）；
- A 放行、B 落人审的格：A 的 5-a 判 same 且命中的库条目是**同一物理格**（`match._cell_parts`，同册同页同列、
  格号差 ≤2）的有多少——这就是「靠自己配自己放行」；
- `--sheet`：从这批格里抽 N 格出联系表（本格字块 | A 命中的库刻例），供人眼确认。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.match import _cell_parts  # noqa: E402


def _pages(expr: str | None, root: Path, book: str) -> list[int]:
    if not expr:
        return sorted(int(f.stem[1:]) for f in (root / book / "seed_admit").glob("p*.json"))
    out: set[int] = set()
    for part in expr.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return sorted(out)


def _read(root: Path, book: str, step: str, page: int, kind: str):
    f = root / book / step / f"p{page:04d}.json"
    if not f.exists():
        return None, None
    raw = f.read_bytes()
    d = json.loads(raw)
    return d.get(kind), hashlib.sha1(json.dumps(d.get(kind), sort_keys=True).encode()).hexdigest()


def _cells(obj, key="chars"):
    for col in (obj or {}).get("columns", []):
        for r in col.get(key, []):
            yield col["col"], r


def same_cell(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    pa, pb = _cell_parts(a), _cell_parts(b)
    return pa is not None and pb is not None and pa[:3] == pb[:3] and abs(pa[3] - pb[3]) <= 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--a", required=True, type=Path)
    ap.add_argument("--b", required=True, type=Path)
    ap.add_argument("--db", required=True)
    ap.add_argument("--pages")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--sheet", type=Path)
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cache", type=Path, help="字块缓存根（GUJI_CACHE_DIR），出联系表用")
    a = ap.parse_args()

    pages = _pages(a.pages, a.a, a.book)
    tot = Counter()
    ch_a, ch_b = Counter(), Counter()
    trans = Counter()                 # (A 通道|review, B 通道|review)
    fell = []                         # A 放行、B 人审
    geom_mismatch = []
    patch_of = {}
    for pg in pages:
        ci_a, ha = _read(a.a, a.book, "cell_shrink", pg, "char_index")
        ci_b, hb = _read(a.b, a.book, "cell_shrink", pg, "char_index")
        if ha != hb:
            geom_mismatch.append(pg)
        for _c, r in _cells(ci_a):
            if r.get("patch_key"):
                patch_of[r["id"]] = r["patch_key"]
        sa, _ = _read(a.a, a.book, "seed_admit", pg, "seed_admit")
        sb, _ = _read(a.b, a.book, "seed_admit", pg, "seed_admit")
        ma, _ = _read(a.a, a.book, "glyph_match", pg, "glyph_match")
        mb, _ = _read(a.b, a.book, "glyph_match", pg, "glyph_match")
        if sa is None or sb is None:
            tot["page_missing"] += 1
            continue
        mrec_a = {r["id"]: r for _c, r in _cells(ma)}
        mrec_b = {r["id"]: r for _c, r in _cells(mb)}
        recs_b = {r["id"]: r for _c, r in _cells(sb)}
        for _c, ra in _cells(sa):
            rb = recs_b.get(ra["id"])
            if rb is None:
                tot["missing_in_b"] += 1
                continue
            tot["cells"] += 1
            exa = "excluded" in (ra.get("doubts") or []) or ra.get("channel") == "excluded"
            ka = ra.get("channel") if ra.get("admit") else "review"
            kb = rb.get("channel") if rb.get("admit") else "review"
            ch_a[ka] += 1
            ch_b[kb] += 1
            trans[(ka, kb)] += 1
            m_a, m_b = mrec_a.get(ra["id"]) or {}, mrec_b.get(ra["id"]) or {}
            tot[f"5a_A_{m_a.get('verdict')}"] += 1
            tot[f"5a_B_{m_b.get('verdict')}"] += 1
            if m_a.get("verdict") == "same" and same_cell(m_a.get("matched_id"), ra["id"]):
                tot["5a_A_same_self"] += 1
            if m_b.get("verdict") == "same" and same_cell(m_b.get("matched_id"), ra["id"]):
                tot["5a_B_same_self"] += 1           # 应为 0：B 摘了同格
            if ra.get("admit") and not rb.get("admit"):
                fell.append({"id": ra["id"], "page": pg, "char_a": ra.get("char"),
                             "channel_a": ka, "match_a": {k: m_a.get(k) for k in
                                                          ("verdict", "char", "matched_id", "cov", "via")},
                             "match_b": {k: m_b.get(k) for k in ("verdict", "char", "matched_id", "cov")},
                             "self_a": bool(m_a.get("verdict") == "same"
                                            and same_cell(m_a.get("matched_id"), ra["id"])),
                             "doubts_b": rb.get("doubts")})
            elif rb.get("admit") and ra.get("admit") and ra.get("char") != rb.get("char"):
                tot["both_auto_char_changed"] += 1
            elif rb.get("admit") and not ra.get("admit"):
                tot["b_only_auto"] += 1
    n = tot["cells"]
    auto_a = n - ch_a["review"]
    auto_b = n - ch_b["review"]
    rep = {
        "book": a.book, "pages": len(pages), "geom_mismatch_pages": geom_mismatch,
        "cells": n, "auto_a": auto_a, "auto_b": auto_b,
        "rate_a": round(auto_a / n, 4) if n else None, "rate_b": round(auto_b / n, 4) if n else None,
        "channels_a": dict(ch_a.most_common()), "channels_b": dict(ch_b.most_common()),
        "transitions": {f"{x}→{y}": v for (x, y), v in trans.most_common() if x != y},
        "fell_to_review": len(fell),
        "fell_self_a": sum(f["self_a"] for f in fell),
        "fell_by_channel_a": dict(Counter(f["channel_a"] for f in fell).most_common()),
        "fell_self_by_channel_a": dict(Counter(f["channel_a"] for f in fell if f["self_a"]).most_common()),
        "counters": dict(tot),
    }
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    rnd = random.Random(a.seed)
    sample = rnd.sample(fell, min(a.sample, len(fell))) if fell else []
    if a.out:
        a.out.write_text(json.dumps({**rep, "sample": sample, "fell": fell}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    if a.sheet and sample:
        _sheet(sample, a, patch_of)
    return 0


def _sheet(sample, a, patch_of) -> None:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from open_guji_cv.clustering.glyph_db import _unpng
    font = ImageFont.truetype(str(REPO / "fonts/iming/I.Ming-8.10.ttf"), 18)
    c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    W, H = 150, 150
    rows = []
    for s in sample:
        pk = patch_of.get(s["id"])
        cell = None
        if pk and a.cache:
            hits = list(a.cache.glob(f"{a.book}/char_patch/**/{pk}.png")) or \
                list(a.cache.glob(f"**/{pk}.png"))
            if hits:
                cell = cv2.imread(str(hits[0]), cv2.IMREAD_GRAYSCALE)
        mid = s["match_a"].get("matched_id")
        lib = None
        lab = "?"
        if mid:
            r = c.execute("SELECT patch_png, label FROM instances WHERE instance_id=?", (mid,)).fetchone()
            if r:
                lib, lab = _unpng(r[0]), r[1]
        tile = Image.new("L", (W * 2 + 360, H + 10), 255)
        for i, im in enumerate((cell, lib)):
            if im is None:
                continue
            h, w = im.shape[:2]
            sc = min((W - 10) / w, (H - 10) / h)
            im2 = cv2.resize(im, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
            tile.paste(Image.fromarray(im2), (i * W + 5, 5))
        d = ImageDraw.Draw(tile)
        txt = (f"格 {s['id']}\n放行字 {s['char_a']}（A:{s['channel_a']}）\n"
               f"A 5-a same → {mid}\n  cov {s['match_a'].get('cov')} 字 {lab}"
               f"{'  ←同格' if s['self_a'] else ''}\n"
               f"B 5-a {s['match_b'].get('verdict')} {s['match_b'].get('char') or ''} {s['match_b'].get('cov')}")
        d.multiline_text((W * 2 + 10, 8), txt, font=font, fill=0, spacing=4)
        rows.append(tile)
    sheet = Image.new("L", (rows[0].width, sum(r.height for r in rows)), 255)
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(a.sheet)
    print("联系表", a.sheet)


if __name__ == "__main__":
    raise SystemExit(main())
