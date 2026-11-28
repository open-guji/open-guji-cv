"""## wu_shape（嗚鳴，第四步 group_flow 的书级刻形判法搬来，2026-11-28）

包的是 `groups.wu_shape.judge`（seed_admit `_wu_shape_pass` 用的同一个函数），吃 `char_patch` 字块图。模型就是第四步那份
书级模型文件（数据目录 `config/groups/wu_shape.json`，`schema: wu_shape/1`），书配置直接指它：
`wu: {ref: wu, trigger: cands, methods: {wu_shape: config/groups/wu_shape.json}}`；也可以给目录，目录里放 `model.json`。

- `sims`：`{鳴: p, 嗚: 1−p}`（p＝`judge` 给的 鳴 概率，已按 4 位小数取整，同第四步 `evidence.wu_shape.p`；1−p 也取 4 位）；
  取不出右半（`abstain:no_ink`）→ `{}`。p 在门槛中间（`abstain:low_p`）仍给 sims，弃权记在证据里。
- `evidence`：`{method: "wu_shape", char, why, p}`，后三键＝`judge()` 返回的整个 dict（第四步 `evidence.wu_shape` 存的就是它，
  无墨弃权没有 `p`）。4d 读时去掉 `method` 就是第四步要存的那份。模型对不对比 `methods_sha` 里的 `wu_shape=<指纹>`
  （`method_fingerprint("wu_shape", group_flow_wu_shape)`）；`model_sha` 与第四步参数指纹 `ws` 段同算法（`wu_shape.fingerprint`）。
- 现役第四步只判**本格字（库首位）是 嗚鳴** 的格（整理本／字组／库前几名有 嗚鳴 都不算）；3b 用 `trigger: cands` 罩住它
  （3a 首位或前 topk 名里有 嗚鳴 就跑），多跑的格 4d 不读。
- 校准：模型文件旁边的 `<文件名去 .json>.calib.json`（给目录时是目录里的 `calib.json`），格式
  `{"format": "near-calib/1", "knots": {"鳴": [[p…], [校准 p…]]}}`，`嗚`＝1−p。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ._base import _dir_fingerprint, _load_calib


class WuShape:
    """嗚鳴 书级刻形判法（`groups.wu_shape`）包成 3b 方法，见模块头「wu_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import wu_shape
        self.model = wu_shape.load(str(self.path))
        self.chars = tuple(self.model.get("chars", ["嗚", "鳴"]))
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`wu_shape.judge` 的结果 → `{鳴: p, 嗚: 1−p}`（p 用 judge 已取整的那个值，不另跑模型）；没有 p → `{}`。"""
        q = v.get("p")
        if q is None:
            return {}
        wu, ming = self.chars
        return {ming: float(q), wu: round(1.0 - float(q), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import wu_shape
        out = []
        for g in patches:
            v = wu_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "wu_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        wu, ming = self.chars
        kn = (self.calib or {}).get("knots", {}).get(ming)
        if not kn or ming not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[ming], xs, ys))
        return {ming: round(p, 4), wu: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `ws` 段同算法（`wu_shape.fingerprint`）。"""
        from .. import wu_shape
        return wu_shape.fingerprint(str(self.path))
