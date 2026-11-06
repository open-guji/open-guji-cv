# -*- coding: utf-8 -*-
"""5a 共识升档参数离线标定（A23 2026-11-06）。

生产已有「共识升档」（`glyph_match.consensus_same`）：unsure 档、没触发护栏、首位字 cov ≥ consensus_cov、
比次优异字高 ≥ consensus_margin、且该字已有 ≥ consensus_min_confirmed 例人裁 → 升 same。
三个参数都是书级软参数（缺省 0.99 / 0.03 / 3），**不用改代码**，只改册 yaml。
这里在 `eval_match_bench.py --rows` 的逐查询结果上重放：生产 same 档不动，unsure 档按候选参数升档，
合并精度 = 答错＋novel 误放。人裁例数按留一：查询自己是库里的一例人裁，首位字 == 金标时减 1。

    python scripts/analyze_match_consensus.py <分片名> <glyph.db> /tmp/out/rows.<分片>.jsonl
"""
import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_match_bench import fold_row  # noqa: E402
from open_guji_cv.steps.glyph_match import consensus_same, human_confirmed_counts  # noqa: E402

COV = (0.95, 0.96, 0.97, 0.98, 0.99)
MARGIN = (0.02, 0.03, 0.04, 0.05)
MINC = (1, 2, 3, 5)


def main() -> None:
    shard, db, rows_path = sys.argv[1:4]
    counts = human_confirmed_counts(db)
    R = [fold_row(json.loads(x)) for x in open(rows_path, encoding="utf-8")]
    R = [r for r in R if r["variant"] == "orig" and not r["sc_flag"]]
    A = [r for r in R if r["answerable"]]
    N = [r for r in R if not r["answerable"]]

    def upgraded(r, cov, margin, minc):
        """该查询最终是否判 same、判的字"""
        if r["verdict"] == "same":
            return r["char"]
        if r["verdict"] != "unsure" or r["guard"] is not None or not r["cand"]:
            return None
        c1 = r["cand"][0][0]
        have = int(counts.get(c1, 0)) - (1 if c1 == r["gold"] else 0)
        hit = consensus_same(r["cand"], lambda c, h=have: h, cov, margin, minc)
        return hit[0] if hit else None

    def run(cov, margin, minc, sub=None):
        a = [r for r in A if sub is None or sub(r)]
        n = [r for r in N if sub is None or sub(r)]
        ok = wrong = 0
        for r in a:
            c = upgraded(r, cov, margin, minc)
            if c is not None:
                ok += c == r["gold"]
                wrong += c != r["gold"]
        fa = sum(upgraded(r, cov, margin, minc) is not None for r in n)
        tot = ok + wrong + fa
        return dict(recall=ok / len(a) if a else 0, prec=ok / tot if tot else None, wrong=wrong, fa=fa, n=len(a))

    print(f"== {shard}  answerable {len(A)} / novel {len(N)}")
    base = run(0.99, 0.03, 3)
    print(f"  缺省 (0.99,0.03,3)        召回 {base['recall']:.3f} 精度 {base['prec']:.4f} 错{base['wrong']}+误放{base['fa']}")
    pts = []
    for c in COV:
        for m in MARGIN:
            for k in MINC:
                e = run(c, m, k)
                if e["prec"] is not None:
                    pts.append(((c, m, k), e))
    for pmin in (0.999, 0.995, 0.99):
        ok = [(p, e) for p, e in pts if e["prec"] >= pmin]
        if not ok:
            print(f"  精度≥{pmin}: 没有参数组合达到")
            continue
        p, e = max(ok, key=lambda t: t[1]["recall"])
        # 二折稳定性：同一组参数在两半页上各自的召回／精度
        halves = []
        for k in (0, 1):
            h = run(*p, sub=lambda r, k=k: zlib.crc32(":".join(r["id"].split(":")[1:3]).encode()) % 2 == k)
            halves.append(f"{h['recall']:.3f}/{h['prec'] if h['prec'] is None else round(h['prec'], 4)}")
        print(f"  精度≥{pmin}: (cov,margin,min_confirmed)={p} 召回 {e['recall']:.3f} 精度 {e['prec']:.4f} "
              f"错{e['wrong']}+误放{e['fa']}  两半页(召回/精度) {halves}")


if __name__ == "__main__":
    main()
