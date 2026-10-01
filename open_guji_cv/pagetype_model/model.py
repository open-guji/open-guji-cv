# -*- coding: utf-8 -*-
"""模型文件：一个 `.joblib`（若干成员分类器 + 各自门槛 + 元数据）+ 同名 `.json` 副本。

合议 = 成员**全部**给出「非正文」得分 > 各自门槛才判非正文（AND）。门槛 = 训练集内折外（OOF）
正文最高得分（加 margin），**不看测试折**——零容忍误判正文。指纹 = 文件字节 sha256 前 16 位，
进 `border_detect_gate` 参数指纹（路径本身不进）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .signals import SIGNAL_VERSION

FORMAT = 1
DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "pagetype" / "pagetype_v1.joblib"


class PageTypeModelError(RuntimeError):
    pass


def file_fingerprint(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


@dataclass
class PageTypeModel:
    members: list          # [{"name", "clf", "features", "thr"}]
    meta: dict
    fingerprint: str

    @property
    def version(self) -> str:
        return f"{self.meta.get('model_id', '?')}@{self.fingerprint}"

    def scores(self, feats: dict) -> dict[str, float]:
        import pandas as pd
        X = pd.DataFrame([feats])
        return {m["name"]: float(m["clf"].predict_proba(X[m["features"]])[0, 1]) for m in self.members}

    def is_nonbody(self, feats: dict) -> tuple[bool, dict[str, float]]:
        sc = self.scores(feats)
        return all(sc[m["name"]] > m["thr"] for m in self.members), sc


def save_model(path: str | Path, members: list, meta: dict) -> str:
    import joblib
    import sklearn
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"format": FORMAT, "signal_version": SIGNAL_VERSION, "sklearn": sklearn.__version__, **meta}
    joblib.dump({"members": members, "meta": meta}, path, compress=3)
    shown = [{"name": m["name"], "features": m["features"], "thr": m["thr"]} for m in members]
    path.with_suffix(".json").write_text(
        json.dumps({**meta, "members": shown, "fingerprint": file_fingerprint(path)}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return file_fingerprint(path)


def load_model(path: str | Path | None = None) -> PageTypeModel:
    import joblib
    import sklearn
    p = Path(path) if path else DEFAULT_MODEL
    try:
        doc = joblib.load(p)
    except OSError as e:
        raise PageTypeModelError(f"页型模型文件读不到：{p}（{e}）") from e
    meta = doc["meta"]
    if meta.get("format") != FORMAT:
        raise PageTypeModelError(f"模型格式 {meta.get('format')} ≠ {FORMAT}")
    if meta.get("signal_version") != SIGNAL_VERSION:
        raise PageTypeModelError(f"模型信号口径 {meta.get('signal_version')} ≠ 当前 {SIGNAL_VERSION}，需重训")
    mm = lambda v: ".".join(str(v).split(".")[:2])  # noqa: E731
    if mm(meta.get("sklearn", "")) != mm(sklearn.__version__):
        raise PageTypeModelError(f"模型用 scikit-learn {meta.get('sklearn')} 训练，当前 {sklearn.__version__}")
    return PageTypeModel(members=doc["members"], meta=meta, fingerprint=file_fingerprint(p))
