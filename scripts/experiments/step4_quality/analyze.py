"""X2 道：现行规则 vs LR / HGB，按页分组交叉验证（GroupKFold，多种子重复）。
用法：python analyze.py dataset.pkl feat_vol01.pkl feat_vol02.pkl [out.json]
"""
from __future__ import annotations

import json
import pickle
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
RULE_FLAGS = ["rule_bar", "edge_blob", "frame_bars", "wide_gap", "off_center", "boundary_ink", "bad_seg"]

GROUPS = {
    "flag_raw": ["rule_bar", "edge_blob", "frame_bars", "x_gap", "off_center", "top_band", "bot_band", "aspect", "bar_crosses"],
    "size": ["p_h", "p_w", "rec_h", "rec_w", "ar_patch", "h_dev", "cell_h", "col_w"],
    "ink": ["ink_ratio", "p_ink", "row_occ", "col_occ", "span_h", "span_w"],
    "cc": ["n_cc", "cc1", "cc2", "cc1_h", "cc1_w", "cc1_cx", "cc1_cy"],
    "edge": ["ink_l", "ink_r", "ink_t", "ink_b"],
    "center": ["cx", "cy"],
    "pos": ["slot", "is_sub", "seal_region"],
}
ALL = [f for g in GROUPS.values() for f in g]


def prep(dsp, fps):
    df = pd.read_pickle(dsp)
    feats = {}
    for p in fps:
        feats.update(pickle.load(open(p, "rb")))
    med = {}
    for (b, pg, c, i), f in feats.items():
        med.setdefault((b, pg), []).append(f["cell_h"])
    med = {k: float(np.median(v)) for k, v in med.items()}
    df["ar_patch"] = df.p_h / df.p_w.clip(lower=1)
    df["h_dev"] = [ch / med[(b, str(p))] - 1 if (b, str(p)) in med and med[(b, str(p))] else 0
                   for ch, b, p in zip(df.cell_h, df.book, df.page)]
    df["bar_crosses"] = df.bar_crosses.fillna(False).astype(float)
    df["seal_region"] = df.flag_seal_region
    df["rule_any"] = df[[f"flag_{f}" for f in RULE_FLAGS]].max(axis=1)
    df["gid"] = df.book + ":" + df.page.astype(str)
    return df


def mk(kind, seed=0):
    if kind == "lr":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000))
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.06, max_iter=150, min_samples_leaf=10,
                                          l2_regularization=1.0, class_weight="balanced", random_state=seed)


def oof(df, feats, kind, reps=5, k=5):
    """多次按页分组 CV：返回每格 OOF 概率的均值（不同切分的平均）。"""
    X = df[feats].astype(float).values
    y = df.y.values
    gids = df.gid.values
    ug = np.unique(gids)
    acc = np.zeros(len(df))
    for r in range(reps):
        rng = np.random.RandomState(r)
        perm = dict(zip(ug, rng.permutation(len(ug))))
        gg = np.array([perm[g] for g in gids])
        p = np.zeros(len(df))
        for tr, te in GroupKFold(k).split(X, y, gg):
            m = mk(kind, r).fit(X[tr], y[tr])
            p[te] = m.predict_proba(X[te])[:, 1]
        acc += p
    return acc / reps


def op_at_fpr(y, s, fpr):
    neg = np.sort(s[y == 0])[::-1]
    t = neg[min(len(neg) - 1, int(np.floor(fpr * len(neg))))] if fpr > 0 else s.max() + 1
    return float((s[y == 1] > t).mean()), float(t)


def op_at_recall(y, s, rec):
    pos = np.sort(s[y == 1])
    t = pos[int(np.floor((1 - rec) * len(pos)))]
    return float((s[y == 0] >= t).mean()), float(t)


def rule_pt(y, r):
    return float(r[y == 1].mean()), float(r[y == 0].mean())


def table(df, name, scores, extra=None):
    out = {}
    y = df.y.values
    rec, fpr = rule_pt(y, df.rule_any.values)
    out["n"] = int(len(df)); out["n_pos"] = int(y.sum())
    out["rule_any"] = {"recall": rec, "fpr": fpr, "precision": float(y[df.rule_any.values == 1].mean()) if df.rule_any.sum() else None}
    for f in RULE_FLAGS:
        r = df[f"flag_{f}"].values
        out[f"flag_{f}"] = {"recall": float(r[y == 1].mean()), "fpr": float(r[y == 0].mean())}
    for k, s in scores.items():
        d = {"auc": float(roc_auc_score(y, s)), "ap": float(average_precision_score(y, s))}
        d["recall_at_rule_fpr"] = op_at_fpr(y, s, fpr)[0]
        d["fpr_at_rule_recall"] = op_at_recall(y, s, rec)[0]
        for tf in (0.05, 0.10):
            d[f"recall_at_fpr{int(tf*100):02d}"] = op_at_fpr(y, s, tf)[0]
        out[k] = d
    # 规则的 raw 单量 AUC（用作基线：最好的单一原始量）
    out["single_best"] = max(((f, float(roc_auc_score(y, df[f].astype(float)))) for f in GROUPS["flag_raw"]), key=lambda t: max(t[1], 1 - t[1]))
    return out


def main():
    df = prep(sys.argv[1], sys.argv[2:4])
    outp = sys.argv[4] if len(sys.argv) > 4 else None
    print(df.groupby(["book", "y"]).size().to_dict())
    res = {}
    scores = {}
    for nm, fs in (("lr_flagraw", GROUPS["flag_raw"]), ("lr_all", ALL), ("hgb_flagraw", GROUPS["flag_raw"]), ("hgb_all", ALL)):
        scores[nm] = oof(df, fs, nm.split("_")[0])
    df_scores = pd.DataFrame(scores, index=df.index)
    df_scores.to_pickle("/tmp/claude-0/s/oof_scores.pkl")
    sets = {
        "A_all(弱+强负)": np.ones(len(df), bool),
        "B_强负only": ((df.y == 1) | (df.strong == 1)).values,
        "C_vol02页位稳定(>=0.9)": ((df.book == "vol02") & (df.page_stab >= 0.9)).values,
        "D_vol01(未验证漂移)": (df.book == "vol01").values,
        "E_仅truncated": ((df["sub"] != "contaminated")).values,
        "F_仅contaminated": ((df["sub"] != "truncated")).values,
    }
    for sn, m in sets.items():
        res[sn] = table(df[m], sn, {k: v[m] for k, v in scores.items()})
    # 消融：HGB，去一组 / 只一组（A 集）
    abl = {}
    y = df.y.values
    full = roc_auc_score(y, scores["hgb_all"]); full_ap = average_precision_score(y, scores["hgb_all"])
    for g, fs in GROUPS.items():
        rest = [f for f in ALL if f not in fs]
        s_drop = oof(df, rest, "hgb", reps=3)
        s_only = oof(df, fs, "hgb", reps=3)
        abl[g] = {"drop_auc": float(roc_auc_score(y, s_drop)), "drop_ap": float(average_precision_score(y, s_drop)),
                  "only_auc": float(roc_auc_score(y, s_only)), "only_ap": float(average_precision_score(y, s_only))}
    res["ablation"] = {"full_auc": float(full), "full_ap": float(full_ap), "groups": abl}
    if outp:
        json.dump(res, open(outp, "w"), ensure_ascii=False, indent=1)
    for sn in sets:
        print("\n==", sn, res[sn]["n"], "pos", res[sn]["n_pos"])
        r = res[sn]
        print(" rule_any", {k: round(v, 3) if v is not None else None for k, v in r["rule_any"].items()})
        for k in scores:
            print(" ", k, {a: round(b, 3) for a, b in r[k].items()})
    print("\nablation", json.dumps(res["ablation"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
