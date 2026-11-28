"""## rr_shape（入人八，第四步 group_flow 的书级刻形判法搬来的样板，2026-11-28）

包的是 `groups.rr_shape.judge`（seed_admit `_rr_shape_pass` 用的同一个函数，同一张图同一个模型逐位同一结论同一分），
吃 `char_patch` 字块图。模型就是第四步那份书级模型文件（数据目录 `config/groups/rr_shape.json`，`schema: rr_shape/1`，
`research/char_groups/rr/qtw_shape_train.py` 导出），书配置直接指它：`methods: {rr_shape: config/groups/rr_shape.json}`；
也可以给目录，目录里放 `model.json`。

- `sims`：几何判成 八 → `{八: 1, 人: 0, 入: 0}`；走逻辑回归 → `{入: σ(s), 人: 1−σ(s), 八: 0}`（s＝`judge` 给的决策值，
  已按 3 位小数取整，同第四步 `evidence.rr_shape.score`）；弃权里没算出 s 的（无墨、组外字护栏、几何不明、NaN）→ `{}`。
  分差不够（`abstain:low_margin`）仍给 sims，弃权记在证据里。
- `evidence`：`{method: "rr_shape", char, why, nn, score, geo}`，后五键与第四步 `evidence.rr_shape` 同键同值（`char` 是现役判法的结论，弃权为 None）。**4d 的读口就是这里**（`seed_admit_shapes._near_from_3b`，开关 `group_flow_near_from_3b`，cv #1999）：按 `NearMethodOut.method` 冒号前是 `rr_shape` 取，证据带 `error` 的格不取；模型对不对比 `methods_sha` 里的 `rr_shape=<指纹>`。
- 校准：模型文件旁边的 `<文件名去 .json>.calib.json`（给目录时是目录里的 `calib.json`），格式
  `{"format": "near-calib/1", "knots": {"入": [[σ(s)…], [p…]]}, "rule": {"八": p}}`：逻辑回归那一路按 knots 映 `入` 的 p、`人`＝1−p；
  几何判 八 的那一路 p 取 `rule.八`。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）；要标就拿训练脚本按册留出那一遍的
  (s, 放行字) 做保序回归，或人裁样本。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ._base import _dir_fingerprint, _sibling_calib


class RrShape:
    """入人八 书级刻形判法（`groups.rr_shape`）包成 3b 方法，见模块头「rr_shape」。"""

    patch = "char_patch"
    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        cal = p / "calib.json" if p.is_dir() else _sibling_calib(p)
        from .. import rr_shape
        self.model = rr_shape.load(str(self.path))
        self.calib = json.loads(cal.read_text(encoding="utf-8")) if cal.is_file() else None
        if self.calib is not None and self.calib.get("format") != "near-calib/1":
            raise ValueError(f"{cal} format 不是 near-calib/1：{self.calib.get('format')!r}")

    @staticmethod
    def sims_of(v: dict) -> dict[str, float]:
        """`rr_shape.judge` 的结果 → 组内各字的分（只由 judge 的结论与决策值算，不另跑模型）。"""
        if v.get("char") == "八" and "score" not in v:
            return {"八": 1.0, "人": 0.0, "入": 0.0}
        s = v.get("score")
        if s is None:
            return {}
        q = round(1.0 / (1.0 + math.exp(-float(s))), 4)
        return {"入": q, "人": round(1.0 - q, 4), "八": 0.0}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import rr_shape
        out = []
        for g in patches:
            v = rr_shape.judge(g, self.model)
            trail = {"method": "rr_shape", **{k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}}
            out.append({"sims": self.sims_of(v), "evidence": trail})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        if not self.calib or not sims:
            return None
        if sims.get("八") == 1.0:
            pb = (self.calib.get("rule") or {}).get("八")
            return None if pb is None else {"八": round(float(pb), 4)}
        kn = (self.calib.get("knots") or {}).get("入")
        if not kn or "入" not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims["入"], xs, ys))
        return {"入": round(p, 4), "人": round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `rs` 段同算法（`rr_shape.fingerprint`），4d 拿它对 `group_flow_rr_shape`。"""
        from .. import rr_shape
        return rr_shape.fingerprint(str(self.path))
