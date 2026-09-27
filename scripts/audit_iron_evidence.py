# -*- coding: utf-8 -*-
"""铁证审计：每个字位只拿**人裁实例**当字形库比对，看「铁证」给的字与现在放行的字是否一致。

    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/audit_iron_evidence.py bxgb \
        --pages 3-56 --out <json>

设计见 overview `进度/总览/14-准确率优先-Step6与Step7重设计.md` §二。铁证口径（用户 2026-09-25 定）：
本格与一个**人裁过的、别的格**的实例比对，top1 cov ≥ 0.99；或 cov ≥ 0.95 且次优**异字**
cov < 0.80。库里 align 来源的实例不参与（只算辅助证据），本格自己的实例摘除。

只出报表，不改任何产物。

**判据实现在** `open_guji_cv.clustering.iron_evidence`（生产 `steps/seed_admit.py` 的
`iron` 通道与这里、`scripts/experiments/shadow_admit/` 共用同一份代码，2026-09-27 转正时
从本文件搬过去的，见模块头的四条护栏）。本文件只剩 CLI 壳与「跟现字比对」这一种报表逻辑。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.iron_evidence import (  # noqa: E402
    IRON_COV, IRON_COV_LOW, IRON_SECOND_MAX, human_matcher, iron,
)

__all__ = ["IRON_COV", "IRON_COV_LOW", "IRON_SECOND_MAX", "human_matcher", "iron"]


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
