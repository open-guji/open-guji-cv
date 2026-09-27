"""a1：两书分数分布与真值排名（只读现成产物，不重算）。

真值两套：
  human  —— 全唐文用户人裁（簇级确认/手打），2851 格
  corpus —— 两书都有：整理本对齐锚定页的 equal/replace 字（四庫=四库光盘版、全唐文=维基）
排名只看产物里存的 top-5 候选（>5 记 6）。
"""
from __future__ import annotations

import collections
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import QTW_BOOKS, QTW_WS, SIKU_WS, align_chars, load_qtw_truth, match_recs  # noqa

REPO = Path(__file__).resolve().parents[3]
_v = json.loads((REPO / "config/variants/variants.json").read_text(encoding="utf-8"))


def rel(a, b):
    if a == b:
        return True
    P, D = _v.get("pairs", {}), _v.get("directed", {})
    return (b in (P.get(a) or {})) or (a in (P.get(b) or {})) or (b in (D.get(a) or {})) or (a in (D.get(b) or {}))


def rank_of(rec, truth):
    for i, (c, _v) in enumerate(rec.get("candidates") or []):
        if rel(c, truth):
            return i + 1, _v
    return 6, None


def summarize(name, pairs):
    """pairs: [(rec, truth_char)]"""
    n = len(pairs)
    if not n:
        return {"name": name, "n": 0}
    ranks = [rank_of(r, t)[0] for r, t in pairs]
    verd = collections.Counter(r.get("verdict") for r, _ in pairs)
    top_cov = [r.get("cov") or 0 for r, _ in pairs]
    truth_cov = [c for (r, t) in pairs for rk, c in [rank_of(r, t)] if c is not None]
    wmax = [r.get("wmax") for r, _ in pairs if r.get("wmax") is not None]
    q = lambda xs, p: (sorted(xs)[int(p * (len(xs) - 1))] if xs else None)
    return {
        "name": name, "n": n,
        "verdict": {k: f"{v/n:.1%}" for k, v in verd.most_common()},
        "top1": f"{sum(1 for x in ranks if x == 1)/n:.1%}",
        "top5": f"{sum(1 for x in ranks if x <= 5)/n:.1%}",
        "not_in_top5": f"{sum(1 for x in ranks if x == 6)/n:.1%}",
        "top_cov_q10/50/90": [q(top_cov, .1), q(top_cov, .5), q(top_cov, .9)],
        "truth_cov_q10/50/90": [q(truth_cov, .1), q(truth_cov, .5), q(truth_cov, .9)],
        "wmax_q10/50/90": [q(wmax, .1), q(wmax, .5), q(wmax, .9)],
    }


def main():
    out = []
    # 四庫 vol03 × 整理本
    m = match_recs(SIKU_WS, "vol03"); a = align_chars(SIKU_WS, "vol03")
    out.append(summarize("vol03 × 四库光盘版(全部锚定格)", [(m[k], a[k]["align_char"]) for k in a if k in m]))
    # 全唐文 × 维基
    pairs = []
    for b in QTW_BOOKS:
        m = match_recs(QTW_WS, b); a = align_chars(QTW_WS, b)
        pairs += [(m[k], a[k]["align_char"]) for k in a if k in m]
    out.append(summarize("全唐文 v006-010 × 维基(全部锚定格)", pairs))
    # 全唐文 × 人裁
    t = load_qtw_truth()
    allm = {}
    for b in QTW_BOOKS:
        allm.update(match_recs(QTW_WS, b))
    hp = [(allm[k], v["char"]) for k, v in t.items() if k in allm]
    out.append(summarize(f"全唐文 × 用户人裁 (命中产物 {len(hp)}/{len(t)})", hp))
    for src in ("batch2", "batch3"):
        out.append(summarize(f"  └ {src}", [(allm[k], v["char"]) for k, v in t.items() if k in allm and v["src"] == src]))
    for o in out:
        print(json.dumps(o, ensure_ascii=False))


if __name__ == "__main__":
    main()
