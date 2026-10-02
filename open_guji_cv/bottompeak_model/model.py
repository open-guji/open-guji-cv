# -*- coding: utf-8 -*-
"""模型文件：一个 `.joblib`（分类器 + 特征名 + 护栏参数 + 元数据）+ 同名 `.json` 副本。

指纹 = 文件字节 sha256 前 16 位，进 `border_detect` 参数指纹（路径本身不进）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .signals import SIGNAL_VERSION

FORMAT = 1
DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "bottompeak" / "bottompeak_v1.joblib"

#: 硬护栏默认值（模型外；训练脚本可在模型文件里覆盖，但**上界/下界不会比这里更松**）。
GUARD_DEFAULTS = {
    "up_slack": 2.0,     # 候选终点比现役终点靠上超过这么多 px → 不采信（宁下勿上，用户 2026-09-13 口径）
    "down_max": 70.0,    # 比现役终点靠下超过这么多 → 不采信
    "margin": 0.10,      # 模型给的概率要比现役线候选高出这么多才换
    "min_prob": 0.30,    # 选中候选的概率下限
}


class BottomPeakModelError(RuntimeError):
    pass


def file_fingerprint(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


@dataclass
class BottomPeakModel:
    clf: object            # predict_proba(DataFrame[features])[:, 1]
    features: list
    guard: dict
    meta: dict
    fingerprint: str

    @property
    def version(self) -> str:
        return f"{self.meta.get('model_id', '?')}@{self.fingerprint}"

    def probs(self, cands: list[dict]):
        import pandas as pd
        X = pd.DataFrame([c["feats"] for c in cands])[self.features]
        return self.clf.predict_proba(X)[:, 1]

    def bind(self, top_pos: float | None):
        """绑定本页上框位置，返回 `find_horizontal_border(bottom_chooser=...)` 要的回调。"""
        from .chooser import make_chooser
        return make_chooser(self, top_pos)


def save_model(path: str | Path, clf, features: list, guard: dict | None, meta: dict) -> str:
    import joblib
    import sklearn
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    g = {**GUARD_DEFAULTS, **(guard or {})}
    meta = {"format": FORMAT, "signal_version": SIGNAL_VERSION, "sklearn": sklearn.__version__, **meta}
    joblib.dump({"clf": clf, "features": list(features), "guard": g, "meta": meta}, path, compress=3)
    path.with_suffix(".json").write_text(
        json.dumps({**meta, "features": list(features), "guard": g, "fingerprint": file_fingerprint(path)},
                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return file_fingerprint(path)


def load_model(path: str | Path | None = None) -> BottomPeakModel:
    import joblib
    import sklearn
    p = Path(path) if path else DEFAULT_MODEL
    try:
        doc = joblib.load(p)
    except OSError as e:
        raise BottomPeakModelError(f"下版框候选模型文件读不到：{p}（{e}）") from e
    meta = doc["meta"]
    if meta.get("format") != FORMAT:
        raise BottomPeakModelError(f"模型格式 {meta.get('format')} ≠ {FORMAT}")
    if meta.get("signal_version") != SIGNAL_VERSION:
        raise BottomPeakModelError(f"模型信号口径 {meta.get('signal_version')} ≠ 当前 {SIGNAL_VERSION}，需重训")
    mm = lambda v: ".".join(str(v).split(".")[:2])  # noqa: E731
    if mm(meta.get("sklearn", "")) != mm(sklearn.__version__):
        raise BottomPeakModelError(f"模型用 scikit-learn {meta.get('sklearn')} 训练，当前 {sklearn.__version__}")
    return BottomPeakModel(clf=doc["clf"], features=doc["features"], guard=doc["guard"], meta=meta,
                           fingerprint=file_fingerprint(p))
