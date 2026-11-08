"""本书字形库的「字自比／互比」字表（`seed_admit.solo_adapt_pct` 用，schema `char_cov_profile/1`）。

每个字至多抽 `--cap` 条刻例，逐条按线上口径匹配（kNN＋精验，排除自身）：
- 自比：同字候选的 cov（同字掉出候选记 0，算进 `miss`，不进百分位）；
- 互比：别的字（非异体）候选的 cov，记每对 (本字, 对手) 的上限；
- 高危字对：对手互比上限 ≥ 本字自比 p10（本字的刻例像对手的程度，赶上了本字自己最弱的那批）。

用法：
    python scripts/char_cov_profile.py --db <工作区>/output/glyph.db --out char_cov_profile.json [--cap 30] [--jobs 4]
产出放中心库数据目录 `config/groups/char_cov_profile.json`（约定位置，`solo_adapt_profile` 不填就找它）。
`--from-jsonl` 直接用已跑好的逐条匹配记录汇总（离线复算用）。
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KNN_K, PER_CHAR, PER_CHAR_TOP = 15, 3, 10     # 同全唐文 glyph_match 书级参数


def _matcher(db_path: str):
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.steps.glyph_match import _with_knn_cap
    m, _ = load_matcher_from_db(GlyphDB(db_path), knn_k=KNN_K)
    return _with_knn_cap(m, PER_CHAR, PER_CHAR_TOP)


def _work(args):
    db_path, idx = args
    m = _matcher(db_path)
    out = []
    for j in idx:
        r = m.match(m._patches[j], exclude_id=m._ids[j])
        out.append({"c": m._chars[j], "cands": [[a, round(float(b), 4)] for a, b in r.candidates[:8]]})
    return out


def run_matches(db_path: str, cap: int, jobs: int, seed: int = 1) -> list[dict]:
    m = _matcher(db_path)
    by = collections.defaultdict(list)
    for j, c in enumerate(m._chars):
        by[c].append(j)
    rng = random.Random(seed)
    todo = []
    for c, js in sorted(by.items()):
        if len(js) >= 2:
            todo += js if len(js) <= cap else rng.sample(js, cap)
    parts = [todo[i::jobs] for i in range(jobs)]
    if jobs == 1:
        return _work((db_path, todo))
    from multiprocessing import Pool
    with Pool(jobs) as pool:
        return [r for part in pool.map(_work, [(db_path, p) for p in parts]) for r in part]


def aggregate(recs, min_cross: float = 0.90) -> dict:
    import numpy as np
    from open_guji_cv.variants import are_variants
    selfv = collections.defaultdict(list)
    cross = collections.defaultdict(float)
    for r in recs:
        c, d = r["c"], dict((a, b) for a, b in r["cands"])
        selfv[c].append(d.get(c, 0.0))
        for a, b in r["cands"]:
            if a != c and b > 0 and not are_variants(a, c):
                cross[(c, a)] = max(cross[(c, a)], b)
    prof = {}
    for c, v in selfv.items():
        nz = [x for x in v if x > 0]
        prof[c] = {"n": len(v), "miss": round(1 - len(nz) / len(v), 3),
                   "p10": round(float(np.percentile(nz, 10)), 4) if nz else 0.0,
                   "p25": round(float(np.percentile(nz, 25)), 4) if nz else 0.0,
                   "med": round(float(np.median(nz)), 4) if nz else 0.0}
    risk = sorted({(a, b) for (a, b), mx in cross.items()
                   if a in prof and prof[a]["n"] >= 5 and mx >= prof[a]["p10"]})
    return {"schema": "char_cov_profile/1", "prof": prof,
            "cross": {f"{a}|{b}": round(mx, 4) for (a, b), mx in sorted(cross.items()) if mx >= min_cross},
            "risk": [list(x) for x in risk]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--from-jsonl", help="已跑好的逐条匹配记录（每行 {c, cands}）")
    a = ap.parse_args(argv)
    if a.from_jsonl:
        recs = [json.loads(line) for line in open(a.from_jsonl, encoding="utf-8")]
    else:
        if not a.db:
            ap.error("要 --db 或 --from-jsonl")
        recs = run_matches(a.db, a.cap, a.jobs)
    prof = aggregate(recs)
    Path(a.out).write_text(json.dumps(prof, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"字 {len(prof['prof'])}，互比 {len(prof['cross'])} 对，高危 {len(prof['risk'])} 对 → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
