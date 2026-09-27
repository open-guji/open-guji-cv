"""a6：自举——拿用户已裁的全唐文格建书级库，留出页不进库，量留出格 top-1。

三种库，都用同一个 GlyphMatcher（HOG kNN + elastic），查询侧预处理同一变体：
  siku       只有四庫库（现役借库）
  qtw        只有全唐文自举库（训练页的人裁格）
  siku+qtw   两者合并
按**页**切分（同页的字不跨训练/留出），种子 0，留出 30% 页。
  python a6_bootstrap.py <qtw_human.pkl> <out.json> [variant]
"""
from __future__ import annotations

import collections
import json
import os
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from a1_score_dist import rel  # noqa: E402
from a4_rematch import QTW_SIZE, SIKU_SIZE, make_variants  # noqa: E402


def build(lib_rows, siku: bool):
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.match import GlyphMatcher
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    if siku:
        m, _ = load_matcher_from_db(GlyphDB(os.environ["GUJI_GLYPH_DB"]), knn_k=10)
    else:
        m = GlyphMatcher(k=10)
    for iid, ch, norm in lib_rows:
        m.add(iid, ch, norm)
    return m


def main():
    pkl, out = sys.argv[1], sys.argv[2]
    var = sys.argv[3] if len(sys.argv) > 3 else "base"
    recs = pickle.load(open(pkl, "rb"))
    V = make_variants(SIKU_SIZE / QTW_SIZE)[var]
    pages = sorted({":".join(r["id"].split(":")[:2]) for r in recs})
    rnd = random.Random(0); rnd.shuffle(pages)
    test_pages = set(pages[: int(len(pages) * 0.3)])
    train, test = [], []
    for r in recs:
        norm = V(r["img"], bool(r.get("punct")))
        (test if ":".join(r["id"].split(":")[:2]) in test_pages else train).append((r["id"], r["truth"], norm))
    res = {"variant": var, "n_train": len(train), "n_test": len(test),
           "train_chars": len({t for _, t, _ in train}), "libs": {}}
    for name, siku, rows in (("siku", True, []), ("qtw", False, train), ("siku+qtw", True, train)):
        m = build(rows, siku)
        top1 = top5 = 0
        per = collections.Counter(); per_ok = collections.Counter()
        for iid, t, norm in test:
            mr = m.match(norm, exclude_id=iid)
            cands = [c for c, _ in mr.candidates[:5]]
            ok1 = bool(cands) and rel(cands[0], t)
            top1 += ok1; top5 += any(rel(c, t) for c in cands)
            per[t] += 1; per_ok[t] += ok1
        n = len(test)
        res["libs"][name] = {"top1": round(top1 / n, 4), "top5": round(top5 / n, 4),
                             "per_char_top1": {c: f"{per_ok[c]}/{per[c]}" for c, _ in per.most_common()}}
        print(name, res["libs"][name]["top1"], res["libs"][name]["top5"], flush=True)
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
