"""汇总 a5：CNN 原型检索 top-1/5/10、真值余弦与首位余弦中位。"""
import json, statistics as st, sys
for f in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f, encoding="utf-8")]
    vs = [k for k in rows[0] if isinstance(rows[0][k], dict)]
    for v in vs:
        R = [r[v] for r in rows]; n = len(R)
        st_ = [x["st"] for x in R if x["st"] is not None]
        print(f"{f.split('/')[-1]:24s} {v:7s} n={n} top1 {sum(x['rank']==1 for x in R)/n:.1%} top5 {sum(x['rank']<=5 for x in R)/n:.1%} "
              f"top10 {sum(x['rank']<=10 for x in R)/n:.1%}  s1_med {st.median(x['s1'] for x in R):.3f}  truth_cos_med {st.median(st_):.3f}")
