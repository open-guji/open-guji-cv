# -*- coding: utf-8 -*-
"""影子放行模型·全书影子运行：用人看过的格训练，对全书每格出影子判定，列出与现字不同的格。

    ~/shadow-venv/bin/python scripts/experiments/shadow_admit/predict.py <signals_all.jsonl> --out <dir>

人看过的格用交叉验证的预测（不拿自己训自己）；其余格用全量模型。
产出：shadow_picks.jsonl（每格一行）、disagree.md（影子≠现字，按把握度排序）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from train import ALL, MODELS, cv_predict  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("signals")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    df = pd.read_json(a.signals, lines=True)
    lab = df[df["label"].notna()].reset_index(drop=True)
    lab["label"] = lab["label"].astype(int)
    unl = df[df["label"].isna()].reset_index(drop=True)

    make = MODELS["梯度提升树"]
    lab["score"] = cv_predict(lab, ALL, make)
    model = make().fit(lab[ALL], lab["label"])
    unl["score"] = model.predict_proba(unl[ALL])[:, 1]
    d = pd.concat([lab, unl], ignore_index=True)

    tot = d.groupby("id")["score"].sum().clip(lower=1e-9)
    idx = d.groupby("id")["score"].idxmax()
    pick = d.loc[idx, ["id", "page", "cand", "cur", "channel", "score", "label"]].rename(columns={"cand": "pick"})
    pick["conf"] = pick["score"] / pick["id"].map(tot)
    cur_score = d[d["cand"] == d["cur"]].set_index("id")["score"]
    pick["cur_score"] = pick["id"].map(cur_score).fillna(0.0)
    pick["labeled"] = pick["id"].isin(set(lab["id"]))
    pick.to_json(out / "shadow_picks.jsonl", orient="records", lines=True, force_ascii=False)

    n = len(pick)
    dis = pick[(pick["pick"] != pick["cur"]) & ~pick["labeled"]].sort_values("conf", ascending=False)
    L = [f"# 影子判定与现字不同的格（未经人看的 {int((~pick['labeled']).sum())} 格中）\n",
         f"全书 {n} 格；影子≠现字 {len(dis)} 格（其中把握 ≥0.8：{int((dis['conf'] >= 0.8).sum())}，≥0.5：{int((dis['conf'] >= 0.5).sum())}）。\n",
         "## 影子把握度分布（未经人看的格）\n\n| 把握 ≥ | 格数 | 占比 |\n|---|---|---|"]
    un = pick[~pick["labeled"]]
    for t in (0.99, 0.95, 0.9, 0.8, 0.5):
        k = int((un["conf"] >= t).sum())
        L.append(f"| {t} | {k} | {k / len(un):.1%} |")
    L.append("\n## 影子≠现字（按把握度）\n\n| 字位 | 现字 | 影子 | 把握 | 现字得分 | 现通道 |\n|---|---|---|---|---|---|")
    L += [f"| {r.id} | {r.cur} | {r.pick} | {r.conf:.2f} | {r.cur_score:.2f} | {r.channel} |" for r in dis.itertuples()]
    (out / "disagree.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:12]))
    print(f"影子≠现字 {len(dis)} 格，见 {out / 'disagree.md'}")


if __name__ == "__main__":
    main()
