"""a5：用**真建出来的库**在维基锚定集上量对照（像素匹配 top-1/top-5）。

  python a5_measure.py <qtw_corpus.pkl> <own.db> <out.json> 名=库路径 ...
  例：siku=四庫库  own=自有库  mixed=自有+四庫

- 测试集 = R 道 `a2_extract.py qtw_corpus` 抽的维基锚定格（每册 600，真值 = 整理本对齐字，
  replace 约占 22%，不干净）；
- 口径：全部 / 真值字在自有库里 / 不在自有库里；
- 查询时排除自己（库里 id 是 `v2:<格>`），测试格本身是人裁格的也照样只排除自己。
"""
from __future__ import annotations

import collections
import json
import pickle
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "qtw_libfail"))
from a1_score_dist import rel  # noqa: E402


def lib_chars(db):
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        return {r[0] for r in c.execute(
            "SELECT DISTINCT g.char FROM exemplars e JOIN glyphs g USING(glyph_id)")}


def main():
    cp, own_db, out = sys.argv[1:4]
    libs = dict(a.split("=", 1) for a in sys.argv[4:])
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.normalize import normalize_patch as N
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    C = pickle.load(open(cp, "rb"))
    chars = lib_chars(own_db)
    res = {"n": len(C), "own_chars": len(chars)}
    per = {}
    for name, dbp in libs.items():
        m, _ = load_matcher_from_db(GlyphDB(dbp), knn_k=10)
        rows = []
        for r in C:
            cands = [c for c, _ in m.match(N(r["img"], isotropic=bool(r.get("punct"))),
                                           exclude_id=f"v2:{r['id']}").candidates[:5]]
            rows.append((r["id"], r["truth"], cands[0] if cands else None,
                         bool(cands) and rel(cands[0], r["truth"]),
                         any(rel(c, r["truth"]) for c in cands)))
        per[name] = rows
        print(name, "done", flush=True)
    inlib = lambda t: t in chars  # noqa: E731
    near = lambda t: t not in chars and any(rel(t, c) for c in chars)  # noqa: E731
    for scope, keep in (("all", lambda t: True), ("真值在自有库", inlib),
                        ("真值只是库里某字的异体", near),
                        ("真值不在自有库", lambda t: not inlib(t) and not near(t))):
        res[scope] = {}
        for name, rows in per.items():
            sel = [x for x in rows if keep(x[1])]
            res[scope][name] = {"n": len(sel), "top1": round(sum(x[3] for x in sel) / max(1, len(sel)), 4),
                                "top5": round(sum(x[4] for x in sel) / max(1, len(sel)), 4)}
    names = list(per)
    res["pairs"] = {}
    for a in names:
        for b in names:
            if a >= b:
                continue
            A = {x[0]: x for x in per[a]}
            fl = collections.Counter()
            lost = collections.Counter()
            for x in per[b]:
                y = A[x[0]]
                k = f"{a}对{b}错" if y[3] and not x[3] else f"{a}错{b}对" if x[3] and not y[3] else "同"
                fl[k] += 1
                if y[3] and not x[3]:
                    lost[x[1]] += 1
            res["pairs"][f"{a}|{b}"] = {"flips": dict(fl), "按真值字_前者对后者错": lost.most_common(30)}
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
