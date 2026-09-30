"""a5：CNN embedding（r5）在四庫真刻例上的检索排名，两书对比 + 预处理变体。

库侧：四庫库全部 exemplar 的 derived.norm → embedding → 按字取均值原型（单位化）。
查询：字块 → 变体预处理 → 64² → embedding，与全部原型余弦，看真值字排第几。
  python a5_cnn.py <patches.pkl> <out.jsonl> [variant ...]
"""
from __future__ import annotations

import json
import os
import pickle
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from a1_score_dist import rel  # noqa: E402
from a4_rematch import QTW_SIZE, SIKU_SIZE, make_variants  # noqa: E402


def main():
    from open_guji_cv.clustering.cnn_candidates import shared
    from open_guji_cv.clustering.seeding import _unpng
    pkl, out, *names = sys.argv[1:]
    names = names or ["base"]
    cnn = shared()
    c = sqlite3.connect(os.environ["GUJI_GLYPH_DB"])
    rows = c.execute("""SELECT g.char, d.data FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
                        JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm'""").fetchall()
    by: dict[str, list] = {}
    for ch, d in rows:
        by.setdefault(ch, []).append(_unpng(d).astype(np.uint8))
    chars = sorted(by)
    protos = []
    for ch in chars:
        e = cnn.embed(by[ch]).mean(0)
        protos.append(e / (np.linalg.norm(e) + 1e-9))
    P = np.stack(protos)
    recs = pickle.load(open(pkl, "rb"))
    with open(out, "w", encoding="utf-8") as fo:
        for i in range(0, len(recs), 64):
            chunk = recs[i:i + 64]
            res = [{"id": r["id"], "book": r["book"], "truth": r["truth"]} for r in chunk]
            for nm in names:
                norms = []
                for r in chunk:
                    sc = SIKU_SIZE / QTW_SIZE if r["book"] != "vol03" else 1.0
                    norms.append(make_variants(sc)[nm](r["img"], bool(r.get("punct"))).astype(np.uint8))
                E = cnn.embed(norms)
                S = E @ P.T
                for j, r in enumerate(chunk):
                    order = np.argsort(-S[j])
                    rk = next((k + 1 for k, idx in enumerate(order[:50]) if rel(chars[idx], r["truth"])), 51)
                    tix = [k for k, ch in enumerate(chars) if rel(ch, r["truth"])]
                    res[j][nm] = {"rank": rk, "top": chars[order[0]], "s1": round(float(S[j, order[0]]), 4),
                                  "st": round(float(S[j, tix].max()), 4) if tix else None}
            for x in res:
                fo.write(json.dumps(x, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
