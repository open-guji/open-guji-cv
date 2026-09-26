# -*- coding: utf-8 -*-
"""影子放行模型 v2：整理本信号拆成关系 / 写法习惯（逐折字对统计）/ 对齐可靠度，与 v1 同一份标签同一折对比。

    ~/shadow-venv/bin/python scripts/experiments/shadow_admit/train_v2.py <signals_all_v2.jsonl> [--report out.md] [--predict-out dir]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).parent))
from train import ALL as V1, MODELS, curve, per_cell  # noqa: E402

# 字对统计（pair_cand/pair_ref/pair_frac，逐折算）实测反而变差：top1 93.8%→92.5%、前 50% 错误率 0.33%→1.81%，
# 样本太少、按字对记数就是在背答案（2026-09-25）。先不进特征，add_pairs 留着备查。
REF2 = ["rel_exact", "rel_variant", "rel_jiajie", "rel_convention", "rel_confusable", "rel_unrelated",
        "ref_run", "ref_local_mismatch"]
V2 = V1 + REF2


def pair_stats(train: pd.DataFrame) -> dict[tuple[str, str], int]:
    """训练折里每个人看过的格：(真值字形, 整理本字) 出现次数。"""
    t = train[train["label"] == 1][["id", "cand", "ref_char"]].drop_duplicates("id")
    return t.groupby(["cand", "ref_char"]).size().to_dict()


def add_pairs(df: pd.DataFrame, stats: dict) -> pd.DataFrame:
    d = df.copy()
    d["pair_cand"] = [stats.get((c, r), 0) if r else 0 for c, r in zip(d["cand"], d["ref_char"])]
    d["pair_ref"] = [stats.get((r, r), 0) if r else 0 for r in d["ref_char"]]
    d["pair_frac"] = (d["pair_cand"] + 0.5) / (d["pair_cand"] + d["pair_ref"] + 1.0)
    return d


def cv_predict2(df: pd.DataFrame, feats: list[str], make) -> np.ndarray:
    p = np.zeros(len(df))
    for tr, te in GroupKFold(n_splits=5).split(df, df["label"], df["page"]):
        st = pair_stats(df.iloc[tr])
        a, b = add_pairs(df.iloc[tr], st), add_pairs(df.iloc[te], st)
        m = make().fit(a[feats], a["label"])
        p[te] = m.predict_proba(b[feats])[:, 1]
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("signals")
    ap.add_argument("--report", default=None)
    ap.add_argument("--predict-out", default=None)
    a = ap.parse_args()
    full = pd.read_json(a.signals, lines=True, dtype={"ref_char": str})
    full["ref_char"] = full["ref_char"].fillna("")
    lab = full[full["label"].notna()].reset_index(drop=True)
    lab["label"] = lab["label"].astype(int)
    L = [f"样本：{lab['id'].nunique()} 格、{len(lab)} 行，按页 5 折（v1/v2 同一折）。\n",
         "| 版本 | top1 | 错格 | 前50%错误率 | 前70% | 前90% | 整理本字≠真值的格 top1 | 同字异体格 top1 |", "|---|---|---|---|---|---|---|---|"]
    ref_wrong = set(lab[(lab["ref_eq"] == 1) & (lab["label"] == 0)]["id"])
    var_cells = set(lab[(lab["label"] == 1) & (lab["rel_variant"] == 1)]["id"]) | \
        set(lab[(lab["label"] == 0) & (lab["rel_exact"] == 1)]["id"]) & set(lab[lab["rel_variant"] == 1]["id"])
    picks = {}
    for name, feats in (("v1", V1), ("v2", V2)):
        pk = per_cell(lab, cv_predict2(lab, feats, MODELS["梯度提升树"]))
        picks[name] = pk
        c = curve(pk)
        sub, sv = pk[pk["id"].isin(ref_wrong)], pk[pk["id"].isin(var_cells)]
        L.append(f"| {name} | {pk['ok'].mean():.1%} | {int((~pk['ok']).sum())} | {c[4][1]:.2%} | {c[6][1]:.2%} | {c[8][1]:.2%} | "
                 f"{sub['ok'].mean():.1%}（{len(sub)}） | {sv['ok'].mean():.1%}（{len(sv)}） |")
    bad = picks["v2"][~picks["v2"]["ok"]].sort_values("conf", ascending=False).head(25)
    L.append("\n## v2 错得最有把握的格（前 25）\n\n| 字位 | 选了 | 真值 | 把握 |\n|---|---|---|---|")
    L += [f"| {r.id} | {r.pick} | {r.truth} | {r.conf:.2f} |" for r in bad.itertuples()]
    text = "\n".join(L)
    print(text)
    if a.report:
        Path(a.report).write_text(text + "\n", encoding="utf-8")
    if a.predict_out:
        out = Path(a.predict_out)
        st = pair_stats(lab)
        lab2 = lab.copy()
        lab2["score"] = cv_predict2(lab, V2, MODELS["梯度提升树"])
        model = MODELS["梯度提升树"]().fit(add_pairs(lab, st)[V2], lab["label"])
        unl = full[full["label"].isna()].reset_index(drop=True)
        unl["score"] = model.predict_proba(add_pairs(unl, st)[V2])[:, 1]
        d = pd.concat([lab2, unl], ignore_index=True)
        tot = d.groupby("id")["score"].sum().clip(lower=1e-9)
        pick = d.loc[d.groupby("id")["score"].idxmax(), ["id", "page", "cand", "cur", "channel", "score"]]
        pick = pick.rename(columns={"cand": "pick"})
        pick["conf"] = pick["score"] / pick["id"].map(tot)
        pick["labeled"] = pick["id"].isin(set(lab["id"]))
        pick.to_json(out / "shadow_picks_v2.jsonl", orient="records", lines=True, force_ascii=False)
        dis = pick[(pick["pick"] != pick["cur"]) & ~pick["labeled"]].sort_values("conf", ascending=False)
        un = pick[~pick["labeled"]]
        M = [f"# 影子 v2 与现字不同的格\n\n未经人看 {len(un)} 格；把握 ≥0.99：{(un['conf'] >= 0.99).mean():.1%}；"
             f"影子≠现字 {len(dis)} 格。\n\n| 字位 | 现字 | 影子 | 把握 | 现通道 |\n|---|---|---|---|---|"]
        M += [f"| {r.id} | {r.cur} | {r.pick} | {r.conf:.2f} | {r.channel} |" for r in dis.itertuples()]
        (out / "disagree_v2.md").write_text("\n".join(M) + "\n", encoding="utf-8")
        print(f"\n影子 v2 ≠ 现字：{len(dis)} 格")


if __name__ == "__main__":
    main()
