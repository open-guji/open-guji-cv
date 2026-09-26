# -*- coding: utf-8 -*-
"""影子放行模型·跨书：A 书训练 → B 书评估；与 B 书自己的按页交叉验证对比，再看 A+B 合训。

    ~/shadow-venv/bin/python scripts/experiments/shadow_admit/transfer.py <A_v2.jsonl> <B_v2.jsonl> [--report out.md]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).parent))
from train import MODELS, curve, per_cell  # noqa: E402
from train_v2 import V1, V2  # noqa: E402


def load(p):
    d = pd.read_json(p, lines=True, dtype={"ref_char": str})
    d["ref_char"] = d["ref_char"].fillna("")
    d = d[d["label"].notna()].reset_index(drop=True)
    d["label"] = d["label"].astype(int)
    return d


def line(name, pk):
    c = curve(pk)
    return (f"| {name} | {pk['ok'].mean():.1%} | {int((~pk['ok']).sum())} | {c[4][1]:.2%} | {c[6][1]:.2%} | "
            f"{c[8][1]:.2%} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--report", default=None)
    x = ap.parse_args()
    A, B = load(x.a), load(x.b)
    make = MODELS["梯度提升树"]
    L = [f"A={Path(x.a).parent.parent.name}：{A['id'].nunique()} 格；B={Path(x.b).parent.parent.name}：{B['id'].nunique()} 格、{B['page'].nunique()} 页。评估一律在 B 上。\n",
         "| 方案 | top1 | 错格 | 前50%错误率 | 前70% | 前90% |", "|---|---|---|---|---|---|"]
    for col, name in (("lib_cov", "单信号·字形库"), ("ocr_p", "单信号·OCR"), ("ref_eq", "单信号·整理本")):
        L.append(line(name, per_cell(B, B[col].to_numpy() + 1e-6 * B["lib_cov"].to_numpy())))
    for fs, fname in ((V1, "v1"), (V2, "v2")):
        m = make().fit(A[fs], A["label"])
        L.append(line(f"A 训 → B（{fname}，零样本迁移）", per_cell(B, m.predict_proba(B[fs])[:, 1])))
        p = np.zeros(len(B))
        for tr, te in GroupKFold(n_splits=5).split(B, B["label"], B["page"]):
            p[te] = make().fit(B.iloc[tr][fs], B.iloc[tr]["label"]).predict_proba(B.iloc[te][fs])[:, 1]
        L.append(line(f"B 自己按页交叉验证（{fname}）", per_cell(B, p)))
        p = np.zeros(len(B))
        for tr, te in GroupKFold(n_splits=5).split(B, B["label"], B["page"]):
            tr_df = pd.concat([A, B.iloc[tr]], ignore_index=True)
            p[te] = make().fit(tr_df[fs], tr_df["label"]).predict_proba(B.iloc[te][fs])[:, 1]
        L.append(line(f"A + B 训练折合训（{fname}）", per_cell(B, p)))
    t = "\n".join(L)
    print(t)
    if x.report:
        Path(x.report).write_text(t + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
