"""X2：用 v2 验证层（instances_v2.json 的 77 条）复测。训练集 = 事件标签集中**不含验证页**的格。
阈值：取全量 OOF 分数上「与现行规则同误报率」「误报 10%」两档（阈值不看验证集）。"""
import sys, json
import numpy as np, pandas as pd
sys.path.insert(0, __import__("os").path.dirname(__file__))
import analyze as A
S = "/tmp/claude-0/s"
tr = A.prep(S + "/dataset.pkl", [S + "/feat_vol01.pkl", S + "/feat_vol02.pkl"])
va = A.prep(S + "/val77.pkl", [S + "/feat_vol01.pkl", S + "/feat_vol02.pkl"])
vp = set(zip(va.book, va.page))
tr2 = tr[[(b, p) not in vp for b, p in zip(tr.book, tr.page)]]
print("train cells", len(tr2), "pos", int(tr2.y.sum()), "| val", len(va), "pos", int(va.y.sum()))
oof = pd.read_pickle(S + "/oof_scores.pkl")
y = tr.y.values
rule_fpr = float(tr.rule_any[tr.y == 0].mean())
out = {"rule_any": {"defect_recall": float(va.rule_any[va.y == 1].mean()), "clean_false_alarm": float(va.rule_any[va.y == 0].mean()),
                    "n_defect": int(va.y.sum()), "n_clean": int((va.y == 0).sum())}}
for nm, fs, kind in (("lr_all", A.ALL, "lr"), ("hgb_all", A.ALL, "hgb"), ("lr_flagraw", A.GROUPS["flag_raw"], "lr"), ("hgb_flagraw", A.GROUPS["flag_raw"], "hgb")):
    ms = [A.mk(kind, s).fit(tr2[fs].astype(float).values, tr2.y.values) for s in range(5 if kind == "hgb" else 1)]
    pr = np.mean([m.predict_proba(va[fs].astype(float).values)[:, 1] for m in ms], axis=0)
    d = {"auc": float(__import__("sklearn.metrics").metrics.roc_auc_score(va.y, pr))}
    for tag, f in (("rule_fpr", rule_fpr), ("fpr10", 0.10)):
        _, t = A.op_at_fpr(y, oof[nm].values, f)
        hit = pr > t
        d[tag] = {"thr": t, "defect_recall": float(hit[va.y == 1].mean()), "clean_false_alarm": float(hit[va.y == 0].mean())}
    d["defect_probs"] = [round(float(v), 3) for v in pr[va.y == 1]]
    d["clean_prob_q50_q90_max"] = [round(float(np.quantile(pr[va.y == 0], q)), 3) for q in (0.5, 0.9, 1.0)]
    out[nm] = d
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(out, open(S + "/val77.json", "w"), ensure_ascii=False, indent=1)
