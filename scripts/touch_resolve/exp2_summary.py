# -*- coding: utf-8 -*-
"""实验二汇总：成对校验按「标签可信」分层，比较 cov / CNN 乘积 / 两者名次相加 三种排序下真字对排第一的比例。
    python scripts/touch_resolve/exp2_summary.py glyph|font
"""
import json, sys
import numpy as np
from common import OUT_ROOT
src = sys.argv[1] if len(sys.argv) > 1 else "glyph"
s = json.load(open(OUT_ROOT / f"exp2_{src}" / "summary.json", encoding="utf-8"))
per = json.load(open(OUT_ROOT / f"exp2_{src}" / "per_case.json", encoding="utf-8"))
e1 = {r["id"]: r for r in json.load(open(OUT_ROOT / "exp1" / "per_case.json", encoding="utf-8"))}
print(f"== exp2_{src}  n={s['n']}  A:", json.dumps(s["A_pair_verify"], ensure_ascii=False))
def strat(rows, name):
    rows = [r for r in rows if r.get("true_top1_cov") is not None]
    if not rows: return
    cov1 = np.mean([r["true_top1_cov"] for r in rows]); cnn1 = np.mean([r["true_top1_cnn"] for r in rows])
    comb = []; inhyp = []
    for r in rows:
        hy = [h for h in r["hyps"] if h["cov"] is not None]
        inhyp.append(r.get("true_in_hyps_by_recog"))
        if len(hy) < 2: comb.append(True); continue
        rank = {h["pair"]: i for i, h in enumerate(sorted(hy, key=lambda h: -h["cov"]))}
        rank2 = {h["pair"]: i for i, h in enumerate(sorted(hy, key=lambda h: -h["cnn"]))}
        best = min(hy, key=lambda h: rank[h["pair"]] + rank2[h["pair"]])
        comb.append(best["pair"] == r["pair"])
    m = np.array([r["margin_cov"] for r in rows])
    print(f"  {name:28s} n={len(rows):3d}  真字对第一: cov {cov1:.1%} | CNN乘积 {cnn1:.1%} | 名次相加 {np.mean(comb):.1%} | 真字对本在识别 3×3 假设集内 {np.mean(inhyp):.1%} | cov 间隔中位 {np.median(m):.3f} p10 {np.percentile(m,10):.3f}")
def label_ok(r):
    rk = e1[r["id"]]["rank"]["gold"]
    return bool(rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5)
strat(per, "all")
ok = [r for r in per if r["id"] in e1 and label_ok(r)]
strat(ok, "label_ok")
strat([r for r in ok if r["verdict"] in ("seam_ok", "moved")], "label_ok/seam_ok+moved")
strat([r for r in ok if r["book"] == "vol02"], "label_ok/vol02")
# 只在「真字对不在识别 3×3 假设集内」的难例上：cov 能否把它捞回？（这些例子里 CNN 乘积对真字对给的分近乎 0）
hard = [r for r in ok if r.get("true_in_hyps_by_recog") is False]
strat(hard, "label_ok & 识别没进假设集")
print("  C 归属后识别:", s["C_recog_after_partition"], "vs chosen", s["C_recog_chosen_cut"])
