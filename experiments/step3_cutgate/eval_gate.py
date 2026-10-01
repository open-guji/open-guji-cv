# -*- coding: utf-8 -*-
"""X3：学习式「送不送人审」闸 vs 现行门槛（PENDING_BLOB=60 / ESCALATE_BLOB=100 / PROBE_DEV=0.10）。
按页分组交叉验证（GroupKFold，页为组，重复 R 次换分组顺序）；曲线 = 送审量 → 漏放的错切数。
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent

NUM_UNET = ["dis", "agree", "agree_margin", "agree_best_other", "dis_min", "dis_straight"]
NUM_CAND = ["n_geo", "n_total", "seam_ink", "dev_max", "seam_ink_max", "dev_max_any"]
NUM_H = ["hu", "hd", "dev_h", "h_min", "h_max", "ink_up", "ink_dn", "ink_min"]
NUM_CTX = ["sub_up", "sub_dn", "raised_up", "raised_dn", "suspect_up", "suspect_dn", "pos_rel", "is_tail",
           "n_cuts_col", "width_rel"]
CAT = ["kind", "origin", "chosen_by"]
GROUPS = {"U-Net(dis/agree/margin…)": NUM_UNET, "候选(n/seam_ink/dev)": NUM_CAND, "格高与墨量": NUM_H,
          "上下文(夹注/抬头/列尾/位置)": NUM_CTX, "类别(kind/origin/chosen_by)": CAT}


def design(df: pd.DataFrame, num: list[str], cat: list[str]) -> pd.DataFrame:
    X = df[num].astype(float).copy()
    for c in cat:
        for v in sorted(df[c].unique()):
            X[f"{c}={v}"] = (df[c] == v).astype(float)
    return X


def oof_scores(df, num, cat, model: str, label: str, repeats=3, seed=0) -> np.ndarray:
    X = design(df, num, cat).values
    y = df[label].values
    pg = (df.book + ":" + df.page.astype(str)).values
    ug = np.unique(pg)
    out = np.zeros((repeats, len(df)))
    for r in range(repeats):
        rng = np.random.RandomState(seed + r)
        perm = {g: i for i, g in enumerate(rng.permutation(ug))}
        gi = np.array([perm[g] for g in pg])
        for tr, te in GroupKFold(5).split(X, y, gi):
            if model == "lr":
                m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                  LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced"))
            else:
                m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150,
                                                   min_samples_leaf=15, l2_regularization=1.0, random_state=r)
            m.fit(X[tr], y[tr])
            out[r, te] = m.predict_proba(X[te])[:, 1]
    return out.mean(0)


def miss_at_volume(score, y, vol_n):
    """送审得分最高的 vol_n 条，漏放的阳性数。"""
    order = np.argsort(-score, kind="stable")
    sent = np.zeros(len(y), bool)
    sent[order[:vol_n]] = True
    return int((y[~sent] == 1).sum())


def vol_for_miss(score, y, miss_target):
    order = np.argsort(-score, kind="stable")
    ys = y[order]
    cum = np.cumsum(ys)
    tot = int(ys.sum())
    need = tot - miss_target
    if need <= 0:
        return 0
    return int(np.searchsorted(cum, need) + 1)


def boot_diff(score, dis, y, pages, n_cur, miss_cur, nb=400, seed=1):
    """页自助：同送审量下 漏放(模型) − 漏放(现行 dis 阈值曲线在同量)。返回均值和 95% 区间。"""
    rng = np.random.RandomState(seed)
    ug = np.unique(pages)
    idx = {g: np.where(pages == g)[0] for g in ug}
    d = []
    for _ in range(nb):
        s = np.concatenate([idx[g] for g in rng.choice(ug, len(ug))])
        yy, sc = y[s], score[s]
        # 现行门槛本身在该重抽样上的送审量与漏放（按各自阈值，不取固定数）
        sent = n_cur[s].astype(bool)
        vol = int(sent.sum())
        miss_now = int(((yy == 1) & ~sent).sum())
        d.append(miss_at_volume(sc, yy, vol) - miss_now)
    d = np.array(d)
    return d.mean(), np.percentile(d, 2.5), np.percentile(d, 97.5)


def report(df, label, tag, repeats, subset=None):
    """OOF 分数在 df 全体上做（按页分组折），指标只在 subset（布尔 mask）上算——page 档不再单独 CV。"""
    df = df.reset_index(drop=True)
    full_scores = None
    sub_idx = np.where(subset)[0] if subset is not None else np.arange(len(df))
    y = df[label].values
    N, P = len(df), int(y.sum())
    pages = (df.book + ":" + df.page.astype(str)).values
    send = df.send_now.values
    n_send, miss = int(send.sum()), int(((y == 1) & (send == 0)).sum())
    print(f"\n### [{tag}] 标签={label}  n={N} 阳性={P}({P/N:.1%})")
    print(f"现行闸(dis≥60 且探针)：送审 {n_send}({n_send/N:.1%})，漏放 {miss}/{P}({miss/P:.1%})，"
          f"送审里命中 {int(((y==1)&(send==1)).sum())}（精度 {((y==1)&(send==1)).sum()/max(1,n_send):.1%}）")
    res = {"n": N, "pos": P, "cur": dict(send=n_send, miss=miss)}
    # 基线：只用 dis 的阈值曲线（与现行同族）
    s_dis = df.dis.values.astype(float)
    print(f"  dis 单特征：AUC {roc_auc_score(y, s_dis):.3f} AP {average_precision_score(y, s_dis):.3f}")
    for thr in (30, 60, 100):
        snt = (s_dis >= thr)
        print(f"    dis≥{thr}: 送审 {snt.sum()}({snt.mean():.1%}) 漏放 {int(((y==1)&~snt).sum())}")
    cfgs = {
        "LR 全特征": (NUM_UNET + NUM_CAND + NUM_H + NUM_CTX, CAT, "lr"),
        "HGB 全特征": (NUM_UNET + NUM_CAND + NUM_H + NUM_CTX, CAT, "hgb"),
    }
    scores = {}
    for name, (num, cat, m) in cfgs.items():
        sc = oof_scores(df, num, cat, m, label, repeats)
        scores[name] = sc
    if subset is not None:
        df = df.iloc[sub_idx].reset_index(drop=True)
        y = df[label].values
        scores = {k: v[sub_idx] for k, v in scores.items()}
        N, P = len(df), int(y.sum())
        pages = (df.book + ":" + df.page.astype(str)).values
        send = df.send_now.values
        n_send, miss = int(send.sum()), int(((y == 1) & (send == 0)).sum())
        s_dis = df.dis.values.astype(float)
        print(f"  [子集 n={N} 阳性={P}] 现行闸 送审 {n_send} 漏放 {miss}")
    print(f"{'模型':<22}{'AUC':>7}{'AP':>7} | 同送审量{n_send}条：漏放(现行{miss}) Δ[95%CI] | 同漏放≤{miss}：需送审(现行{n_send})")
    for name, sc in scores.items():
        m_same = miss_at_volume(sc, y, n_send)
        v_same = vol_for_miss(sc, y, miss)
        d, lo, hi = boot_diff(sc, s_dis, y, pages, send, miss)
        print(f"{name:<22}{roc_auc_score(y, sc):7.3f}{average_precision_score(y, sc):7.3f} | "
              f"{m_same:>4}  Δ{m_same-miss:+d} [{lo:+.0f},{hi:+.0f}] | {v_same:>5}  Δ{v_same-n_send:+d}")
        res[name] = dict(auc=roc_auc_score(y, sc), ap=average_precision_score(y, sc), miss_same_vol=m_same, vol_same_miss=v_same,
                         boot=[d, lo, hi])
    # dis 阈值曲线在同送审量的漏放（基线曲线）
    print(f"  参照 dis 阈值曲线同量({n_send}条)漏放：{miss_at_volume(s_dis, y, n_send)}；同漏放需送审：{vol_for_miss(s_dis, y, miss)}")
    return res, scores


def ablation(df, label, repeats, model="hgb"):
    y = df[label].values
    send = df.send_now.values
    n_send, miss = int(send.sum()), int(((y == 1) & (send == 0)).sum())
    allnum = NUM_UNET + NUM_CAND + NUM_H + NUM_CTX
    print(f"\n#### 消融（{model}，标签={label}；指标 = 同送审量 {n_send} 条的漏放数 / AP；全特征基线先报）")
    base = oof_scores(df, allnum, CAT, model, label, repeats)
    print(f"  全特征                     miss={miss_at_volume(base, y, n_send):>3} AP={average_precision_score(y, base):.3f}")
    rows = {}
    for g, cols in GROUPS.items():
        num = [c for c in allnum if c not in cols]
        cat = [c for c in CAT if c not in cols]
        sc = oof_scores(df, num, cat, model, label, repeats)
        rows[g] = (miss_at_volume(sc, y, n_send), average_precision_score(y, sc))
        print(f"  去掉 {g:<28} miss={rows[g][0]:>3} AP={rows[g][1]:.3f}")
    for g, cols in GROUPS.items():
        num = [c for c in allnum if c in cols]
        cat = [c for c in CAT if c in cols]
        sc = oof_scores(df, num, cat, model, label, repeats)
        print(f"  只用 {g:<28} miss={miss_at_volume(sc, y, n_send):>3} AP={average_precision_score(y, sc):.3f}")


def probe_experiment(df, label, repeats):
    """第二个决策：要不要过 U-Net 探针。特征不含任何 U-Net 量。目标 = 探针之后的结论会是「送审」(dis≥60)；
    同时报对「真错切」的覆盖。现行 PROBE_DEV 规则 = probed_now。"""
    y = label_y = df[label].values
    tgt = (df.dis >= 60).astype(int).values
    df = df.copy(); df["_tgt"] = tgt
    pr = df.probed_now.values
    nP = int(pr.sum())
    print(f"\n#### 探针门槛（PROBE_DEV）：现行 探 {nP}/{len(df)}({nP/len(df):.1%})；覆盖 dis≥60 的 {int(((tgt==1)&(pr==1)).sum())}/{int(tgt.sum())}；"
          f"覆盖真错({label}) {int(((y==1)&(pr==1)).sum())}/{int(y.sum())}")
    num = [c for c in NUM_CAND if c != "n_total"] + NUM_H + NUM_CTX     # n_total 含扩池结果（dis≥60 才扩），泄漏目标
    for name, lab in (("目标=探后会送审(dis≥60)", "_tgt"), (f"目标=真错({label})", label)):
        sc = oof_scores(df, num, [c for c in CAT if c != "chosen_by"], "hgb", lab, repeats)
        yy = df[lab].values
        order = np.argsort(-sc)
        sent = np.zeros(len(df), bool); sent[order[:nP]] = True
        print(f"  HGB(无U-Net特征) {name}: 同探量{nP}：覆盖 dis≥60 {int((sent&(tgt==1)).sum())}/{int(tgt.sum())}，"
              f"覆盖真错 {int((sent&(y==1)).sum())}/{int(y.sum())}；"
              f"AUC({name.split('=')[0]}) {roc_auc_score(yy, sc):.3f}")
    # 现行 vs 模型在 dis≥60 覆盖上，各探量比例曲线
    sc = oof_scores(df, num, [c for c in CAT if c != "chosen_by"], "hgb", "_tgt", repeats)
    print("  探量比例 → 覆盖 dis≥60 的比例（HGB / 现行点）")
    for f in (0.1, 0.2, 0.3, 0.4, 0.5, 0.7):
        k = int(f * len(df)); o = np.argsort(-sc)[:k]
        s = np.zeros(len(df), bool); s[o] = True
        print(f"    探 {f:.0%}：覆盖 {(s&(tgt==1)).sum()/tgt.sum():.1%} / 真错 {(s&(y==1)).sum()/y.sum():.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=str(HERE / "out/table.csv"))
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    df = pd.read_csv(a.table)
    print("表:", len(df), df.src.value_counts().to_dict())
    df["lab_cur_noov"] = df.lab_cur
    noov = df[df.verdict != "overlap"].reset_index(drop=True)
    print("overlap（物理重叠，切哪都伤字）行数:", int((df.verdict == "overlap").sum()), "→ noov 变体剔除")
    for label, d0 in (("lab_verdict", df), ("lab_cur", df), ("lab_cur_noov", noov)):
        report(d0, label, "全部", a.repeats)
        report(d0, label, "仅 page 档（可信）", a.repeats, subset=(d0.src == "gold_page").values)
    ablation(df, "lab_verdict", a.repeats)
    ablation(noov, "lab_cur_noov", a.repeats)
    probe_experiment(noov, "lab_cur_noov", a.repeats)
    probe_experiment(df, "lab_verdict", a.repeats)


if __name__ == "__main__":
    main()
