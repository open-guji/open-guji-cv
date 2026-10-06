"""第三步（overview#442）：并入 17 格人裁后的最终评测。推荐配置＝4 类（含「其他」）rf + 质量闸，阈值 0.5。
训练仍只用弱标签（不含强真值、不含 vol04）；评测在全部强真值上，按册、按「是否分类器挑出来的格」分层。"""
import json, collections, sys
import numpy as np
sys.argv = sys.argv[:1]
import clf2 as C
from feat import DS, CLS
from scipy.stats import beta
def cp(k, n):  # Clopper-Pearson 95%
    lo = 0 if k == 0 else beta.ppf(0.025, k, n - k + 1); hi = 1 if k == n else beta.ppf(0.975, k + 1, n - k)
    return round(float(lo), 3), round(float(hi), 3)
R, F, Q, m = C.R, C.F, C.Q, C.m_all
V = {json.loads(l)["id"]: json.loads(l)["verdict"] for l in open(DS.replace("/rr", "") + "/review/rr17_verdicts.jsonl", encoding="utf-8")}
S = [r for r in R if C.strong(r) and r["id"] in F]
def run(thr, gate):
    out = collections.defaultdict(lambda: [0, 0, 0]); errs = []
    for r in S:
        grp = ("rr17" if r["id"] in V else "其他强真值")
        for key in ((r["book"], grp), ("全部", grp), ("全部", "合计")):
            out[key][0] += 1
        if gate and C.gated(Q[r["id"]]): continue
        d = C.decide(m.predict_proba(F[r["id"]].reshape(1, -1))[0], thr)
        if not d: continue
        for key in ((r["book"], grp), ("全部", grp), ("全部", "合计")):
            out[key][1] += 1; out[key][2] += d == r["gold"]
        if d != r["gold"]: errs.append((r["id"], r["gold"], d))
    return out, errs
res = {}
for thr, gate in ((0.5, True), (0.5, False), (0.8, True)):
    out, errs = run(thr, gate)
    print(f"\n== thr {thr} 质量闸{'开' if gate else '关'}   错: {errs}")
    for k in sorted(out):
        n, g, ok = out[k]; ci = cp(ok, g) if g else None
        print(f"  {k[0]:6s}{k[1]:8s} 强真值{n:3d} 给字{g:3d}({g/n:.0%}) 对{ok:3d} 准确{ok/max(g,1):.1%} CI{ci} 弃权{n-g}({(n-g)/n:.0%})")
    res[f"{thr}|{gate}"] = {f"{a}|{b}": v for (a, b), v in out.items()}
json.dump(res, open(DS + "/clf_eval_v2.json", "w"), ensure_ascii=False, indent=1)
# 放行格里人裁 vs 放行字
adm = [r for r in R if r["id"] in V and V[r["id"]] != "unclear" and r["admit"]]
print("\n分歧/放行格人裁 vs 放行字:", sum(V[r["id"]] == r["char"] for r in adm), "/", len(adm), "放行对；放行错", [(r["id"], r["char"], V[r["id"]]) for r in adm if V[r["id"]] != r["char"]])
print("其中整理本也错:", [(r["id"], r["ref"]) for r in adm if V[r["id"]] != r["char"]])
# 分类器 vs 人裁（17 格逐格，4 类模型 p≥0.5）
print("\n逐格（rr17）：")
for r in R:
    if r["id"] in V:
        p = m.predict_proba(F[r["id"]].reshape(1, -1))[0]; d = C.decide(p, 0.5)
        print(r["id"], "人裁", V[r["id"]], "放行", r["char"] if r["admit"] else "待审", "整理本", r["ref"], "分类器", d, "p=%.2f" % p.max(), "闸" if C.gated(Q[r["id"]]) else "")
