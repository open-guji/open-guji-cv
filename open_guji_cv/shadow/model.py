# -*- coding: utf-8 -*-
"""影子模型文件：一个 `.joblib`（分类器 + 元数据）+ 同名 `.json`（元数据副本，给人看）。

元数据 `meta`（训练脚本 `scripts/shadow_gate_train.py` 写）：

    format           文件格式版本（现为 1）
    model_id         人起的名字，如 "shadow_gate_v1"
    signal_version   信号口径版本（`signals.SIGNAL_VERSION`）；不等就拒绝加载
    features         特征列表（顺序即训练顺序）
    classifier       分类器描述
    calibration      校准方式（见下）
    train_books      训练书目 {书: 标签格数}
    n_cells / n_rows 训练标签格数／行数
    cv_commit        训练时 cv 仓 HEAD
    sklearn          训练用 scikit-learn 版本（major.minor 不同拒绝加载：pickle 跨版本不保）
    trained_at       UTC 时间
    notes            自由说明（含训练折、已知局限）

校准：`HistGradientBoosting.predict_proba` 的 (字位, 候选) 概率，**逐格归一**成「把握度」
（一格内候选分数和为 1，取最大者）；**没有另做等渗校准**（vol03 标签只有 334 格，校准集太小）。
门槛因此是「实测错误率」定的，不是概率定的（见 HANDOFF_N1.md）。

指纹 = 模型文件字节的 sha256 前 16 位：进 `seed_admit` 参数指纹，路径本身不进（`StepSpec.path_params`）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .signals import FEATURES, SIGNAL_VERSION

FORMAT = 1
DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "shadow_admit" / "shadow_gate_v1.joblib"


class ShadowModelError(RuntimeError):
    pass


def file_fingerprint(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


@dataclass
class ShadowModel:
    clf: object
    meta: dict
    fingerprint: str

    @property
    def version(self) -> str:
        return f"{self.meta.get('model_id', '?')}@{self.fingerprint}"

    def scores(self, rows: list[dict]) -> list[float]:
        import pandas as pd
        X = pd.DataFrame(rows)[list(self.meta["features"])]
        return [float(v) for v in self.clf.predict_proba(X)[:, 1]]


def save_model(path: str | Path, clf, meta: dict) -> str:
    import joblib
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import sklearn
    meta = {"format": FORMAT, "signal_version": SIGNAL_VERSION, "features": list(FEATURES),
            "sklearn": sklearn.__version__, **meta}
    joblib.dump({"clf": clf, "meta": meta}, path, compress=3)
    path.with_suffix(".json").write_text(
        json.dumps({**meta, "fingerprint": file_fingerprint(path)}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return file_fingerprint(path)


def load_model(path: str | Path | None = None) -> ShadowModel:
    import joblib
    import sklearn
    p = Path(path) if path else DEFAULT_MODEL
    try:
        doc = joblib.load(p)
    except OSError as e:
        raise ShadowModelError(f"影子模型文件读不到：{p}（{e}）") from e
    meta = doc["meta"]
    if meta.get("format") != FORMAT:
        raise ShadowModelError(f"模型格式 {meta.get('format')} ≠ {FORMAT}")
    if meta.get("signal_version") != SIGNAL_VERSION:
        raise ShadowModelError(f"模型信号口径 {meta.get('signal_version')} ≠ 当前 {SIGNAL_VERSION}，需重训")
    mm = lambda v: ".".join(str(v).split(".")[:2])  # noqa: E731
    if mm(meta.get("sklearn", "")) != mm(sklearn.__version__):
        raise ShadowModelError(f"模型用 scikit-learn {meta.get('sklearn')} 训练，当前 {sklearn.__version__}")
    return ShadowModel(clf=doc["clf"], meta=meta, fingerprint=file_fingerprint(p))
