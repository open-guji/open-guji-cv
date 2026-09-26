# -*- coding: utf-8 -*-
"""铁证审计：每个字位只拿**人裁实例**当字形库比对，看「铁证」给的字与现在放行的字是否一致。

    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/audit_iron_evidence.py bxgb \
        --pages 3-56 --out <json>

设计见 overview `进度/总览/14-准确率优先-Step6与Step7重设计.md` §二。铁证口径（用户 2026-09-25 定）：
本格与一个**人裁过的、别的格**的实例比对，top1 cov ≥ 0.99；或 cov ≥ 0.95 且次优**异字**
cov < 0.80。库里 align 来源的实例不参与（只算辅助证据），本格自己的实例摘除。

只出报表，不改任何产物。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

IRON_COV = 0.99
IRON_COV_LOW = 0.95
IRON_SECOND_MAX = 0.80


def human_matcher(db_path: str, norm_stroke: int | None):
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.match import GlyphMatcher
    from open_guji_cv.clustering.normalize import normalize_patch
    import numpy as np
    db = GlyphDB(db_path)
    m = GlyphMatcher(k=10)
    rows = db.conn.execute(
        """SELECT g.char, e.instance_id, i.patch_png FROM exemplars e
           JOIN glyphs g ON g.glyph_id = e.glyph_id
           JOIN instances i ON i.instance_id = e.instance_id
           WHERE i.label_status = 'human'""").fetchall()
    for char, iid, png in rows:
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            m.add(iid, char, normalize_patch(img, stroke_width=norm_stroke))
    return m, len(rows)


def iron(cands: list[tuple[str, float]], human_chars: set[str],
         partners: dict[str, frozenset[str]]) -> tuple[str | None, float, float, str]:
    """→ (铁证字 | None, top cov, 次优异字 cov, 不成铁证的原因)。

    用户口径（cov ≥ 0.99；或 ≥ 0.95 且次优 < 0.80）之外加两条护栏——p20 试跑实测需要：
    - **两个人裁字都 ≥ 0.99** 不算铁证（且 0.9961 / 旦 0.9935：两份人裁证据互相打架）；
    - **形近对家不在人裁库里**不算铁证：cov 对一点一横不敏感，人裁库只有「太」没有「大」时，
      刻本的「大」对「太」能到 0.994（match.py 护栏 1 注释里记过同一个盲区）。
    """
    if not cands:
        return None, 0.0, 0.0, "无候选"
    top_c, top_v = cands[0]
    second = max((v for c, v in cands[1:] if c != top_c), default=0.0)
    if not (top_v >= IRON_COV or (top_v >= IRON_COV_LOW and second < IRON_SECOND_MAX)):
        return None, top_v, second, "分数不够"
    if second >= IRON_COV:
        return None, top_v, second, "两个人裁字都像"
    missing = sorted(partners.get(top_c, frozenset()) - human_chars)
    if missing:
        return None, top_v, second, "形近对家未入人裁库:" + "".join(missing[:5])
    return top_c, top_v, second, ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--pages", default="3-56")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.core.book import load_book
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import page_slots
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    from open_guji_cv.utils.image_io import imread

    bk = load_book(a.book)
    ns = getattr(bk, "norm_stroke", None)
    matcher, n_lib = human_matcher(GlyphMatchParams().db_path, ns)
    from open_guji_cv.clustering.confusable import partners as _partners
    partners = _partners()
    human_chars = set(matcher._chars)
    vm = VariantMap.load()
    st, cache = ProductStore(), ImageCache()
    lo, _, hi = a.pages.partition("-")
    rows, stat = [], Counter()
    for pg in range(int(lo), int(hi or lo) + 1):
        for s in page_slots(st, a.book, pg):
            if not s.is_text or s.char in (None, "□"):
                continue
            ck = f"p{pg:04d}c{s.col:02d}s{s.slot}{s.sub or ''}"
            path = cache.get(a.book, "char_patch", ck)
            if path is None:
                stat["无图块"] += 1
                continue
            img = imread(str(path), cv2.IMREAD_GRAYSCALE)
            res = matcher.match(normalize_patch(img, stroke_width=ns), exclude_id=f"v2:{s.id}")
            cands = [(c, float(v)) for c, v in res.candidates]
            if res.verdict == "same" and res.char and all(c != res.char for c, _ in cands):
                cands.insert(0, (res.char, float(res.cov)))
            cands.sort(key=lambda t: -t[1])
            ic, top, second, why = iron(cands, human_chars, partners)
            cur = s.char
            if ic is None:
                kind = "无铁证:" + why.split(":")[0]
            elif ic == cur:
                kind = "一致"
            elif vm.semantic(ic) == vm.semantic(cur):
                kind = "同字异形"
            else:
                kind = "冲突"
            stat[kind] += 1
            if kind in ("冲突", "同字异形"):
                rows.append({"id": s.id, "kind": kind, "cur": cur, "reading": s.reading,
                             "channel": s.channel, "iron": ic, "cov": round(top, 4),
                             "second": round(second, 4), "matched": res.matched_id,
                             "cands": [(c, round(v, 4)) for c, v in cands[:5]]})
    Path(a.out).write_text(json.dumps({"n_human_exemplars": n_lib, "stat": stat, "rows": rows},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"人裁实例 {n_lib}；", dict(stat))


if __name__ == "__main__":
    main()
