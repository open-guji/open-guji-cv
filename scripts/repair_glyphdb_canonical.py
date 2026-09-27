# -*- coding: utf-8 -*-
"""修复人裁刻例的 canonical 图（2026-09-19）。

    GUJI_WORKSPACE=<ws> python scripts/repair_glyphdb_canonical.py --book bxgb [--dry-run]

## 修什么

`feedback/consumers.glyphdb_admit` 进库前用 `binarize_page` 二值化字块，而那个函数自
2026-09-17 起在最外 20px **强制判纸**（挡整页扫描的纸缘渐变）。字块只有 64×88 上下，四边
各抹 20px 之后只剩中间一小块：09-18/19 入库的 405 条人裁刻例 canonical 里字高只有画布的
0.12（正常 0.26），归一后笔画断成碎片；拿字位自己现在的图块去查库，自身相似度中位 0.43、
99% 低于 0.7（09-16/17 入库的 380 条：0.88、2%）。人裁 7 次的「宐」候选里根本不出现。

## 怎么修

对每条 `admissions.provenance='human'` 的实例：从 `cache/<book>/char_patch/` 取现在的字块，
用修好的二值化（`edge_margin=0`）→ `to_canonical` → 覆盖 `instances.patch_png`，并按
`admit_instance` 同一套路重算 `derived`（norm / skeleton / feat）。glyphs / exemplars /
admissions 不动——它们记的是「人裁了哪个字」，没错。

只覆盖 canonical 字高明显偏小（< 0.18 画布）的；正常的一条不碰，`--dry-run` 先报数。
改完库指纹变了，glyph_match 起会自动过期，要 `pipeline --from glyph_match` 重跑。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.clustering.canonical import encode_png, to_canonical  # noqa: E402
from open_guji_cv.clustering.glyph_db import _now, GlyphDB  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.core.workspace import glyph_db_path  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.utils.binarized import binarize_page  # noqa: E402

CANVAS = 256
SMALL = 0.18      # canonical 字高 / 画布 低于此判「被纸缘留白啃过」；正常 0.26，坏的 0.12


def glyph_height(png: bytes) -> int:
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0
    ys = np.where((img < 128).any(axis=1))[0]
    return int(ys[-1] - ys[0] + 1) if len(ys) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="不看字高，人裁刻例全部重算")
    a = ap.parse_args()
    db = GlyphDB(str(glyph_db_path()))
    cache = ImageCache()
    cur = db.conn.cursor()
    rows = cur.execute(
        "SELECT a.instance_id, i.patch_png FROM admissions a JOIN instances i "
        "ON i.instance_id = a.instance_id WHERE a.provenance='human' "
        "AND a.instance_id LIKE ?", (f"v2:{a.book}:%",)).fetchall()
    n_small = n_fixed = n_missing = 0
    heights_before: list[float] = []
    for iid, png in rows:
        h0 = glyph_height(png) / CANVAS
        heights_before.append(h0)
        if not a.all and h0 >= SMALL:
            continue
        n_small += 1
        _v, book, pg, col, slot = iid.split(":")
        sub = ""
        if slot and slot[-1] in "ab":
            slot, sub = slot[:-1], slot[-1]
        ckey = f"p{int(pg):04d}c{int(col):02d}s{int(slot)}{sub}"
        path = cache.get(book, "char_patch", ckey)
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
        if img is None:
            n_missing += 1
            continue
        binv = binarize_page(img, edge_margin=0)
        canon = to_canonical(binv)
        new_png = encode_png(canon)
        if a.dry_run:
            n_fixed += 1
            continue
        # 与 GlyphDB.refresh_instance_patch 同一纪律：改了图块/派生就要碰时间戳——
        # 库指纹（db_fingerprint）与特征矩阵常驻缓存都只看 exemplars.added_at，
        # 只换 derived 它们看不见（2026-09-19 第一版没碰，靠的是当时指纹还含 mtime）
        now = _now()
        cur.execute("UPDATE instances SET patch_png=?, updated_at=? WHERE instance_id=?",
                    (new_png, now, iid))
        db._write_derived(cur, iid, normalize_patch(canon))
        cur.execute("UPDATE exemplars SET added_at=? WHERE instance_id=?", (now, iid))
        n_fixed += 1
    if not a.dry_run:
        db.conn.commit()
    hb = np.array(heights_before) if heights_before else np.array([0.0])
    print(f"人裁刻例 {len(rows)} 条；canonical 字高/画布 中位 {np.median(hb):.2f}，< {SMALL} 的 {int((hb < SMALL).sum())} 条")
    print(f"{'试算' if a.dry_run else '已修'} {n_fixed} 条（缺字块 {n_missing}）")
    if not a.dry_run and n_fixed:
        after = [glyph_height(r[0]) / CANVAS for r in cur.execute(
            "SELECT i.patch_png FROM admissions a JOIN instances i ON i.instance_id=a.instance_id "
            "WHERE a.provenance='human' AND a.instance_id LIKE ?", (f"v2:{a.book}:%",)).fetchall()]
        print(f"修后 canonical 字高/画布 中位 {np.median(after):.2f}，< {SMALL} 的 {sum(1 for x in after if x < SMALL)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
