# -*- coding: utf-8 -*-
"""replace 位采信学习模型·页分组交叉验证 + 与现行闸（长度闸 ∧ 库证据闸）正面比（R1 道）。

    python research/replace_gate/train_eval.py rows.jsonl --out report/ [--repeats 20]

标签 `gold_ok`（采对）；模型分数 = P(采对)。曲线：把阈值从高扫到低，每点 = (采信量 A, 错采数 W)，
都在**有人裁标签**的格上数。现行闸是一个点（不是曲线）：A_cur, W_cur。
对比口径：同错采数（≤ W_cur）下模型最多采信多少；同采信量（≥ A_cur）下模型最少错采多少。
折按 (book,page) 分组，重复 `--repeats` 次随机分折，指标报均值±标准差；全程只有页内行相关的泄漏被隔开。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

GROUPS = {
    "seg": ["len", "pos", "prev", "next", "flank_min", "flank_max"],
    "loc": ["slot", "col", "is_sub", "col_len", "slot_rel"],
    "page": ["page_slots", "page_rep_rate", "page_eq_rate", "page_n_ops", "an_votes", "an_frac", "an_dom"],
    "lib": ["m_cov", "m_nver", "m_wmax", "lib_s1", "lib_gap", "lib_n", "lib_eq_gold", "lib_eq_hyp",
            "lib_var_gold", "lib_gold_rank", "lib_gold_score", "m_unsure", "m_same"],
    "rel": ["var_hg", "conf_hg"],
    "rare": ["rare_has", "rare_gold_rank_bin", "rare_top1_gold", "rare_top1_hyp"],
    "segcons": ["seg_mean_cov", "seg_min_cov", "seg_n_var", "seg_n_libconf", "seg_other_libconf"],
}
ALL = [f for g in GROUPS.values() for f in g]


def load(path):
    R = [json.loads(l) for l in open(path, encoding="utf-8")]
    for r in R:
        r["m_unsure"] = int(r["m_verdict"] == "unsure"); r["m_same"] = int(r["m_verdict"] == "same")
        g = r["rare_gold_rank"]
        r["rare_gold_rank_bin"] = -1 if g < 0 else 0 if g == 0 else min(g, 10)
    return R


def mat(R, feats):
    return np.array([[float(r[f]) for f in feats] for r in R])


def make(kind):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "lr":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000))
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=15,
                                          l2_regularization=1.0, random_state=0)


def oof_scores(R, feats, kind, seed, n_splits=5):
    from sklearn.model_selection import GroupKFold
    X = mat(R, feats); y = np.array([int(r["gold_ok"]) for r in R])
    pg = sorted({(r["book"], r["page"]) for r in R})
    rng = np.random.RandomState(seed); perm = rng.permutation(len(pg)); pid = {pg[i]: k for k, i in enumerate(perm)}
    g = np.array([pid[(r["book"], r["page"])] % n_splits for r in R])
    s = np.zeros(len(R))
    for f in range(n_splits):
        tr, te = g != f, g == f
        if len(set(y[tr])) < 2:
            s[te] = 1.0; continue
        m = make(kind)
        if kind == "hgb":
            w = np.where(y[tr] == 0, (y[tr] == 1).sum() / max(1, (y[tr] == 0).sum()), 1.0)
            m.fit(X[tr], y[tr], sample_weight=np.clip(w, 1, 30))
        else:
            m.fit(X[tr], y[tr])
        s[te] = m.predict_proba(X[te])[:, 1]
    return s


def curve(score, ok):
    """按分数降序逐个加入：返回 (A, W) 数组，A=采信量，W=其中错采数；同分一起进。"""
    o = np.argsort(-score, kind="stable")
    sc, okk = score[o], ok[o]
    A = np.arange(1, len(o) + 1); W = np.cumsum(~okk.astype(bool))
    last = np.r_[sc[1:] != sc[:-1], True]
    return A[last], W[last]


def at_w(A, W, w_max):
    i = np.where(W <= w_max)[0]
    return int(A[i[-1]]) if len(i) else 0


def at_a(A, W, a_min):
    i = np.where(A >= a_min)[0]
    return int(W[i[0]]) if len(i) else int(W[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows"); ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=20)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    R = load(a.rows)
    H = [r for r in R if r["gold_ok"] is not None]
    ok = np.array([bool(r["gold_ok"]) for r in H])
    cur = np.array([bool(r["cur_adopt"]) for r in H])
    lg = np.array([bool(r["len_gate"]) for r in H]); lk = np.array([bool(r["lib_gate_keep"]) for r in H])
    A_cur, W_cur = int(cur.sum()), int((cur & ~ok).sum())
    res = {"n_all": len(R), "n_labeled": len(H), "n_ok": int(ok.sum()), "n_bad": int((~ok).sum()),
           "cur": {"A": A_cur, "W": W_cur, "len_only_A": int(lg.sum()), "len_only_W": int((lg & ~ok).sum()),
                   "lib_only_A": int(lk.sum()), "lib_only_W": int((lk & ~ok).sum())}, "models": {}}
    print(f"标签 {len(H)}（采对 {ok.sum()}、采错 {(~ok).sum()}）；现行闸 采信 {A_cur} 错采 {W_cur}")
    configs = {"lr": ("lr", ALL), "hgb": ("hgb", ALL)}
    for g in GROUPS:
        configs[f"hgb-{g}"] = ("hgb", [f for f in ALL if f not in GROUPS[g]])     # 消融：去掉一组
    configs["hgb-only-len+lib"] = ("hgb", GROUPS["seg"] + GROUPS["lib"] + GROUPS["rel"])   # 近似现行闸信号的最小集
    curves = {}
    for name, (kind, feats) in configs.items():
        Aw, Wa, Wsame, curve_pts = [], [], [], []
        for r in range(a.repeats if name in ("lr", "hgb") else max(5, a.repeats // 4)):
            s = oof_scores(H, feats, kind, seed=r)
            A, W = curve(s, ok)
            Aw.append(at_w(A, W, W_cur)); Wa.append(at_a(A, W, A_cur))
            Wsame.append(at_w(A, W, 0))
            if r == 0:
                curve_pts = [(int(x), int(y)) for x, y in zip(A, W)]
        res["models"][name] = {"A_at_W<=Wcur": [float(np.mean(Aw)), float(np.std(Aw))],
                               "W_at_A>=Acur": [float(np.mean(Wa)), float(np.std(Wa))],
                               "A_at_W0": [float(np.mean(Wsame)), float(np.std(Wsame))]}
        if name in ("lr", "hgb"):
            curves[name] = curve_pts
        print(f"{name:<18s} 同错采≤{W_cur}：采信 {np.mean(Aw):6.1f}±{np.std(Aw):4.1f}  │ 同采信≥{A_cur}：错采 {np.mean(Wa):5.2f}±{np.std(Wa):4.2f}"
              f"  │ 零错采：采信 {np.mean(Wsame):6.1f}±{np.std(Wsame):4.1f}", flush=True)
    res["curves_seed0"] = curves
    # 非现行闸格（长段、没夹住）的人裁子集：模型在「全体同错采≤W_cur」阈值下放进来多少
    ng = np.array([not r["len_gate"] for r in H]); long4 = np.array([r["len"] >= 4 for r in H])
    for kind in ("lr", "hgb"):
        n_ng, n_l4, bad_ng = [], [], []
        for r in range(a.repeats):
            sc = oof_scores(H, ALL, kind, seed=r)
            o = np.argsort(-sc, kind="stable"); W = np.cumsum(~ok[o]); i = np.where(W <= W_cur)[0]
            t = sc[o][i[-1]] if len(i) else 2.0
            adm = sc >= t
            n_ng.append(int((adm & ng).sum())); n_l4.append(int((adm & long4).sum())); bad_ng.append(int((adm & ng & ~ok).sum()))
        res.setdefault("relax", {})[kind] = {"nongate_labeled": int(ng.sum()), "nongate_adopted": float(np.mean(n_ng)),
                                            "long4_labeled": int(long4.sum()), "long4_adopted": float(np.mean(n_l4)),
                                            "nongate_adopted_bad": float(np.mean(bad_ng))}
        print(f"放宽 {kind}: 非闸内人裁 {int(ng.sum())}（≥4字 {int(long4.sum())}）→ 模型在同错采阈值下放进 {np.mean(n_ng):.1f}（≥4字 {np.mean(n_l4):.1f}，其中错 {np.mean(bad_ng):.2f}）")
    # 待标名单：没人裁、不在现行闸内的位，按 LR 全量拟合分数从低到高（最拿不准的先标）
    m = make("lr"); m.fit(mat(H, ALL), np.array([int(r["gold_ok"]) for r in H]))
    U = [r for r in R if r["gold_ok"] is None and not r["len_gate"]]
    if U:
        su = m.predict_proba(mat(U, ALL))[:, 1]
        with open(out / "to_label.tsv", "w", encoding="utf-8") as f:
            f.write("id\tlen\tprev\tnext\thyp\tgold\tlr_score\n")
            for r, v in sorted(zip(U, su), key=lambda t: t[1]):
                f.write(f"{r['id']}\t{r['len']}\t{r['prev']}\t{r['next']}\t{r['hyp']}\t{r['gold']}\t{v:.3f}\n")
        res["to_label"] = len(U)
    # 曲线 CSV + 图
    import csv
    with open(out / "curves.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["model", "adopted", "wrong"])
        for k, pts in curves.items():
            for A_, W_ in pts:
                w.writerow([k, A_, W_])
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 4.2))
        for k, pts in curves.items():
            ax.plot([x for x, _ in pts], [y for _, y in pts], label=k)
        ax.scatter([A_cur], [W_cur], c="k", marker="*", s=120, zorder=5, label=f"current gates ({A_cur},{W_cur})")
        ax.set_xlabel("adopted (human-labeled cells)"); ax.set_ylabel("wrongly adopted"); ax.set_xlim(700, len(H)); ax.set_ylim(0, 16); ax.legend()
        fig.tight_layout(); fig.savefig(out / "curve.png", dpi=120)
    except Exception as e:  # 没装 matplotlib 就只留 CSV
        print("画图跳过：", e)
    # 长段（≥4 字）：现行一律不采，模型放宽后的表现
    long_ = np.array([r["len"] >= 4 for r in H])
    res["long"] = {"labeled": int(long_.sum()), "bad": int((long_ & ~ok).sum())}
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
