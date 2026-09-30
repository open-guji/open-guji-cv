"""a2：抽字块（现场从原图 + 产物重建），存成 pickle 供后续量与重比对。

用法：GUJI_WORKSPACE=<ws> python a2_extract.py <set> <out.pkl>
  set = qtw_human   全唐文人裁 2851 格
        qtw_corpus  全唐文维基锚定格，每册均匀抽 600
        vol03       四庫 vol03 光盘版锚定格，均匀抽 3000
"""
from __future__ import annotations

import os
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import QTW_BOOKS, QTW_WS, SIKU_WS, align_chars, load_qtw_truth, match_recs  # noqa


def ctx_for(book):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    return RunContext(load_book(book), ProductStore(), ImageCache(), log=lambda *_: None)


def patch_keys(ws, book):
    import glob, json
    out = {}
    for f in glob.glob(str(ws / "products" / book / "cell_shrink" / "p*.json")):
        d = json.load(open(f))["char_index"]
        for col in d["columns"]:
            for r in col.get("chars") or []:
                if r.get("patch_key") and r.get("cell_type") == "char":
                    out[r["id"]] = r
    return out


def main():
    which, out = sys.argv[1], sys.argv[2]
    rnd = random.Random(0)
    jobs = []  # (book, cell_id, truth)
    if which == "qtw_human":
        for k, v in load_qtw_truth().items():
            jobs.append((k.split(":")[0], k, v["char"]))
    elif which == "qtw_corpus":
        for b in QTW_BOOKS:
            a = align_chars(QTW_WS, b)
            ks = sorted(a); rnd.shuffle(ks)
            jobs += [(b, k, a[k]["align_char"]) for k in ks[:600]]
    elif which == "vol03":
        a = align_chars(SIKU_WS, "vol03")
        ks = sorted(a); rnd.shuffle(ks)
        jobs += [("vol03", k, a[k]["align_char"]) for k in ks[:3000]]
    recs = []
    by_book = {}
    for b, k, t in jobs:
        by_book.setdefault(b, []).append((k, t))
    for b, items in by_book.items():
        ctx = ctx_for(b)
        ws = SIKU_WS if b == "vol03" else QTW_WS
        pk = patch_keys(ws, b)
        for k, t in items:
            r = pk.get(k)
            if not r:
                continue
            try:
                img = ctx.image("char_patch", r["patch_key"])
            except Exception as e:  # noqa
                continue
            recs.append({"book": b, "id": k, "truth": t, "img": img,
                         "punct": r.get("step3_kind") == "punct"})
        print(b, len(items), "→", sum(1 for x in recs if x["book"] == b), flush=True)
    pickle.dump(recs, open(out, "wb"))


if __name__ == "__main__":
    main()
