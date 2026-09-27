# -*- coding: utf-8 -*-
"""影子放行模型·训练与评估（在 ~/shadow-venv 里跑：scikit-learn + pandas，不进主 venv）。

    ~/shadow-venv/bin/python scripts/experiments/shadow_admit/train.py <signals_labeled.jsonl> [--report out.md]

按页分组 5 折交叉验证；逐 (字位, 候选) 二分类 → 每格取概率最大的候选。报告：
top1、「影子放行比例—错误率」曲线、单信号基线、按信号组消融、按情形分层。
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

GROUPS = {
    "字形库": ["lib_cov", "lib_in", "lib_top1", "lib_margin", "lib_top_cov", "human_n", "human_any"],
    "OCR": ["ocr_p", "ocr_rank", "ocr_top1", "ocr_missing"],
    "5b生僻字": ["rare_score"],
    "整理本": ["ref_eq", "ref_sem", "ref_none", "ref_op_equal"],
    "形近": ["confusable"],
    "小笔画": ["disc_d", "disc_has", "disc_margin"],
    "其他": ["n_cands"],
}
ALL = [f for g in GROUPS.values() for f in g]
MODELS = {
    "逻辑回归": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0)),
    "梯度提升树": lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                                    l2_regularization=1.0, random_state=0),
}


def cv_predict(df: pd.DataFrame, feats: list[str], make) -> np.ndarray:
    p = np.zeros(len(df))
    for tr, te in GroupKFold(n_splits=5).split(df, df["label"], df["page"]):
        m = make().fit(df.iloc[tr][feats], df.iloc[tr]["label"])
        p[te] = m.predict_proba(df.iloc[te][feats])[:, 1]
    return p


def per_cell(df: pd.DataFrame, score: np.ndarray) -> pd.DataFrame:
    d = df.assign(score=score)
    idx = d.groupby("id")["score"].idxmax()
    pick = d.loc[idx, ["id", "cand", "score", "cur", "channel", "ref_eq"]].rename(columns={"cand": "pick"})
    truth = d[d["label"] == 1].groupby("id")["cand"].first()
    pick["truth"] = pick["id"].map(truth)
    pick["ok"] = pick["pick"] == pick["truth"]
    # 概率归一到一格内（每格候选的分数和为 1），作为「这格有多确定」
    tot = d.groupby("id")["score"].sum()
    pick["conf"] = pick["score"] / pick["id"].map(tot).clip(lower=1e-9)
    return pick


def curve(pick: pd.DataFrame, key: str = "conf") -> list[tuple[float, float, int]]:
    """按把握度从高到低放行：放行比例 → 放行部分错误数/率。"""
    s = pick.sort_values(key, ascending=False)
    wrong = (~s["ok"]).cumsum().to_numpy()
    n = len(s)
    rows = []
    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        k = max(1, int(n * frac))
        rows.append((frac, wrong[k - 1] / k, int(wrong[k - 1])))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("signals")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    df = pd.read_json(a.signals, lines=True)
    df = df[df["label"].notna()].reset_index(drop=True)
    df["label"] = df["label"].astype(int)
    cells = df["id"].nunique()
    covered = df.groupby("id")["label"].max().sum()
    L: list[str] = []
    L.append(f"样本：{cells} 格（真值在候选集内 {covered}），{len(df)} 行，{df['page'].nunique()} 页；按页 5 折交叉验证。\n")

    L.append("## 单信号基线（每格取该信号最高的候选）\n\n| 基线 | top1 |\n|---|---|")
    for name, col in (("字形库 cov", "lib_cov"), ("OCR 概率", "ocr_p"), ("整理本", "ref_eq"), ("5b 得分", "rare_score")):
        pk = per_cell(df, df[col].to_numpy() + 1e-6 * df["lib_cov"].to_numpy())
        L.append(f"| {name} | {pk['ok'].mean():.1%} |")

    results = {}
    for mname, make in MODELS.items():
        p = cv_predict(df, ALL, make)
        pk = per_cell(df, p)
        results[mname] = pk
        L.append(f"\n## {mname}（全部信号）\n\ntop1 **{pk['ok'].mean():.1%}**（错 {int((~pk['ok']).sum())} 格）\n")
        L.append("| 按把握度放行前 | 放行部分错误率 | 错格数 |\n|---|---|---|")
        for frac, err, nw in curve(pk):
            L.append(f"| {frac:.0%} | {err:.2%} | {nw} |")
        # 分层：整理本与真值不一致的格（正是 䣛 那一型）
        hard = pk[pk["truth"].notna()]
        ref_wrong = df[(df["ref_eq"] == 1) & (df["label"] == 0)]["id"].unique()
        sub = hard[hard["id"].isin(ref_wrong)]
        L.append(f"\n整理本字≠真值的格：{len(sub)} 格，top1 {sub['ok'].mean():.1%}")

    L.append("\n## 按信号组消融（梯度提升树，去掉一组后的 top1 与前 50% 放行错误率）\n\n| 去掉 | top1 | 前50%错误率 |\n|---|---|---|")
    for g, fs in GROUPS.items():
        feats = [f for f in ALL if f not in fs]
        pk = per_cell(df, cv_predict(df, feats, MODELS["梯度提升树"]))
        L.append(f"| {g} | {pk['ok'].mean():.1%} | {curve(pk)[4][1]:.2%} |")

    lr = MODELS["逻辑回归"]().fit(df[ALL], df["label"])
    coef = sorted(zip(ALL, lr[-1].coef_[0]), key=lambda t: -abs(t[1]))
    L.append("\n## 逻辑回归系数（标准化后，全量拟合）\n\n| 信号 | 系数 |\n|---|---|")
    L += [f"| {f} | {c:+.2f} |" for f, c in coef]

    gb = results["梯度提升树"]
    bad = gb[~gb["ok"]].sort_values("conf", ascending=False).head(25)
    L.append("\n## 梯度提升树错得最有把握的格（前 25）\n\n| 字位 | 选了 | 真值 | 把握 | 现通道 |\n|---|---|---|---|---|")
    L += [f"| {r.id} | {r.pick} | {r.truth} | {r.conf:.2f} | {r.channel} |" for r in bad.itertuples()]
    text = "\n".join(L)
    print(text)
    if a.report:
        open(a.report, "w", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    main()
