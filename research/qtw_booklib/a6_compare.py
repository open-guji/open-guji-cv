"""a6：跑批前后对照（A = 借四庫库，B = 全唐文自有库），从 glyph_match 到 seed_admit，Step1–4 不动。

  GUJI_WORKSPACE=$QTW_WS python a6_compare.py <imp_dir> <out.json> <products_A> <products_B> [book ...]

报：放行率 / 人审率 / 各通道放行数；放行字与**不在库里的**人裁格（no_glyph_lib 的 2063 格，
在库里的人裁格会自己匹配到自己，不能拿来核）及维基锚定字的一致率；新放行格（B 放 A 不放）
按通道抽 40 格出拼图供目检。
"""
from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from qb_common import QTW_BOOKS, align_chars, cell_index, ctx_for  # noqa: E402


def main():
    d, out, pa, pb = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    books = sys.argv[5:] or list(QTW_BOOKS)
    final = [json.loads(l) for l in open(d / "final.jsonl", encoding="utf-8")]
    L = json.load(open(d / "lib_keys.json", encoding="utf-8"))
    in_lib = {k for ks in L["lib"].values() for k in ks}
    human = {r["key"]: r["char"] for r in final if r["import"] and r["act"] == "confirm"}
    human_out = {k: v for k, v in human.items() if k not in in_lib}
    res = {"books": books}
    newly = []
    for tag, root in (("A", pa), ("B", pb)):
        tot = collections.Counter()
        ch_ct = collections.Counter()
        hv = collections.Counter()
        wv = collections.Counter()
        for b in books:
            S = _admit(root, b)
            W = align_chars(b)
            for k, r in S.items():
                tot["cells"] += 1
                if r.get("admit"):
                    tot["admit"] += 1
                    ch_ct[r.get("channel")] += 1
                    if k in human_out:
                        hv["ok" if r["char"] == human_out[k] else "bad"] += 1
                    if k in W:
                        wv["ok" if r["char"] == W[k]["align_char"] else "bad"] += 1
                elif r.get("excluded"):
                    tot["excluded"] += 1
                else:
                    tot["review"] += 1
        res[tag] = {**tot, "admit_rate": round(tot["admit"] / tot["cells"], 4),
                    "review_rate": round(tot["review"] / tot["cells"], 4),
                    "by_channel": dict(ch_ct.most_common()),
                    "human_out_of_lib": dict(hv), "wiki_anchor": dict(wv)}
    for b in books:
        A, B = _admit(pa, b), _admit(pb, b)
        for k, r in B.items():
            if r.get("admit") and not (A.get(k) or {}).get("admit"):
                newly.append((b, k, r.get("channel"), r["char"]))
    res["newly_admitted"] = len(newly)
    res["newly_by_channel"] = dict(collections.Counter(x[2] for x in newly).most_common())
    lost = []
    for b in books:
        A, B = _admit(pa, b), _admit(pb, b)
        lost += [k for k, r in A.items() if r.get("admit") and not (B.get(k) or {}).get("admit")]
    res["no_longer_admitted"] = len(lost)
    # 抽 40 格：按通道占比分层
    rnd = random.Random(20260927)
    by = collections.defaultdict(list)
    for x in newly:
        by[x[2]].append(x)
    quota = {c: max(1, round(40 * len(v) / max(1, len(newly)))) for c, v in by.items()}
    sample = []
    for c, v in by.items():
        rnd.shuffle(v)
        sample += v[: quota[c]]
    sample = sample[:40]
    res["sample"] = [{"book": b, "key": k, "channel": c, "char": ch} for b, k, c, ch in sample]
    if sample:
        T = 96
        tiles = []
        for b, k, c, ch in sample:
            cells = cell_index(b)
            im = ctx_for(b).image("char_patch", cells[k]["patch_key"])
            h, w = im.shape[:2]
            s = (T - 8) / max(h, w)
            im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            t = np.full((T, T), 255, np.uint8)
            y0, x0 = (T - im.shape[0]) // 2, (T - im.shape[1]) // 2
            t[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
            tiles.append(t)
        while len(tiles) % 8:
            tiles.append(np.full((T, T), 255, np.uint8))
        grid = np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)])
        cv2.imwrite(str(Path(out).with_suffix(".png")), grid)
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "sample"}, ensure_ascii=False, indent=1))
    for i, x in enumerate(res["sample"]):
        print(i, x["key"], x["channel"], x["char"])


def _admit(root: Path, book: str) -> dict:
    out = {}
    for f in sorted((root / book / "seed_admit").glob("p*.json")):
        sa = json.load(open(f, encoding="utf-8"))
        sa = sa[next(iter(sa))]
        for col in sa["columns"]:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


if __name__ == "__main__":
    main()
