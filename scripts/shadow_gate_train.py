# -*- coding: utf-8 -*-
"""训练影子放行闸的模型文件（带元数据 + 指纹）。

    python scripts/shadow_gate_train.py --out models/shadow_admit/shadow_gate_v1.joblib \
        --train bxgb=<bxgb signals_labeled.jsonl> --train vol02=<vol02 signals_labeled_v2_clean.jsonl> \
        --train-snap vol03=<extract_snap 的 signals_vol03.jsonl> [--model-id shadow_gate_v1] [--notes ...]

输入口径：
- `--train 书=文件`：`extract.py`（读图版）出的信号，过 `vol03_eval.load_train`（剔只有 OCR 提名的候选、己已巳合并）；
- `--train-snap 书=文件`：`extract_snap.py`（快照版）出的信号，只取带 `label` 的格。
特征只用 `open_guji_cv.shadow.signals.FEATURES`（12 个，不含 OCR／小笔画判别器／ref_op_equal）。
分类器与实验一致：HistGradientBoosting(max_iter=300, lr=0.05, max_leaf_nodes=15, l2=1.0, seed 0)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "experiments" / "shadow_admit"))


def make_clf():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                          l2_regularization=1.0, random_state=0)


def load_snap(path: str) -> pd.DataFrame:
    from vol03_eval import J  # noqa: E402
    d = pd.read_json(path, lines=True, dtype={"ref_char": str, "cand": str, "cur": str})
    d = d[d["label"].notna()].copy()
    d["label"] = d["label"].astype(int)
    d["cand"] = d["cand"].map(J)
    return d.reset_index(drop=True)


def main() -> None:
    from open_guji_cv.shadow.model import save_model
    from open_guji_cv.shadow.signals import FEATURES
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--train", action="append", default=[], help="书=extract.py 信号文件")
    ap.add_argument("--train-snap", action="append", default=[], help="书=extract_snap.py 信号文件")
    ap.add_argument("--model-id", default="shadow_gate_v1")
    ap.add_argument("--notes", default="")
    ap.add_argument("--holdout-mod", default="", help="M:i——快照信号里 页号 %% M == i 的页不进训练（评估用的按页折）")
    a = ap.parse_args()
    from vol03_eval import load_train
    parts, books = [], {}
    for spec in a.train:
        b, p = spec.split("=", 1)
        d = load_train(p)
        parts.append(d)
        books[b] = int(d["id"].nunique())
    for spec in a.train_snap:
        b, p = spec.split("=", 1)
        d = load_snap(p)
        if a.holdout_mod:
            m, i = (int(x) for x in a.holdout_mod.split(":"))
            d = d[d["page"] % m != i]
        parts.append(d)
        books[b] = int(d["id"].nunique())
    df = pd.concat(parts, ignore_index=True)
    clf = make_clf().fit(df[list(FEATURES)], df["label"])
    import sklearn
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    fp = save_model(a.out, clf, {
        "model_id": a.model_id,
        "classifier": "HistGradientBoostingClassifier(max_iter=300, lr=0.05, max_leaf_nodes=15, l2=1.0, seed=0)",
        "calibration": "无单独校准：逐格归一 predict_proba 作把握度；门槛按实测错误率定（见 HANDOFF_N1.md）",
        "train_books": books, "n_cells": int(df["id"].nunique()), "n_rows": int(len(df)),
        "cv_commit": commit, "sklearn": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": a.notes,
    })
    print(f"{a.out}  指纹 {fp}  训练 {books} 共 {df['id'].nunique()} 格 {len(df)} 行")


if __name__ == "__main__":
    main()
