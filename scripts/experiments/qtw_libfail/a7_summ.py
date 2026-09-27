"""汇总 a4 重比对结果：每变体 top-1/top-5、判档分布、cov/ink 中位；可按 --in-lib 只看库里有的字。"""
import collections
import json
import statistics as st
import sys

rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
if "--in-lib" in sys.argv:
    rows = [r for r in rows if r.get("in_lib")]
vars_ = [k for k in rows[0] if isinstance(rows[0][k], dict)]
n = len(rows)
print(f"n={n}  (库里有真值字的 {sum(1 for r in rows if r.get('in_lib'))})")
print(f"{'variant':14s} {'top1':>6s} {'top5':>6s} {'top10':>6s} {'same':>5s} {'diff':>5s} {'cov50':>6s} {'tcov50':>6s} {'wmax50':>6s} {'ink50':>6s}")
for v in vars_:
    R = [r[v] for r in rows]
    t1 = sum(x["rank"] == 1 for x in R) / n
    t5 = sum(x["rank"] <= 5 for x in R) / n
    t10 = sum(x["rank"] <= 10 for x in R) / n
    vd = collections.Counter(x["v"] for x in R)
    tc = [x["tcov"] for x in R if x["tcov"] is not None]
    print(f"{v:14s} {t1:6.1%} {t5:6.1%} {t10:6.1%} {vd['same']/n:5.1%} {vd['diff']/n:5.1%} "
          f"{st.median(x['cov'] for x in R):6.3f} {st.median(tc) if tc else 0:6.3f} "
          f"{st.median(x['wmax'] for x in R):6.1f} {st.median(x['ink'] for x in R):6.3f}")
