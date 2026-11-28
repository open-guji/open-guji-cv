"""## hou_shape（候𠋫，第四步 group_flow 的书级刻形判法搬来，2026-11-28）

包的是 `groups.hou_shape.judge`（seed_admit `_hou_shape_pass` 主遍与 `group_flow_hou_shape_late` 晚跑遍用的同一个函数），
吃 `char_patch` 字块图。模型就是第四步那份书级文件（数据目录 `config/groups/hou_shape.json`），书配置直接指它：
`hou: {ref: hou, trigger: cands, methods: {hou_shape: config/groups/hou_shape.json}}`；也可以给目录，目录里放 `model.json`。
两种 schema：

- `hou_shape/2`（小网）：`judge` 给 候 的概率 p（4 位）→ `sims`＝`{候: p, 𠋫: 1−p}`，同 wu_shape。
- `hou_shape/1`（几何量）：`judge` 给 亻 右边第二竖的相对长 v（4 位），`v < lo` 判 候、`v ≥ hi` 判 𠋫、其间弃权。v 不是概率，
  3b 用一个**与现役判定一致的单调映射**出分：`候 = σ(ln9 · (lo + hi − 2v) / (hi − lo))`、`𠋫 = 1 − 候`（各取 4 位）。
  v＝lo 时 候＝0.9、v＝(lo+hi)/2 时 0.5、v＝hi 时 0.1，所以现役判 候 的格 候 ≥ 0.9、判 𠋫 的格 候 ≤ 0.1，弃权的格在 (0.1, 0.9)，
  最高分的字总是现役判的那个字；v 越长越像 𠋫，保序（校准表可直接拿它做保序回归）。`hi − lo < 0.001`（几乎没有中间档）时按判出的字给 1／0（弃权 0.5）。
- 无墨弃权（`abstain:no_ink`）→ `{}`；弃权在中间（`abstain:mid`）仍给 sims。
- `evidence`：`{method: "hou_shape", char, why, v|p}`，后三键＝`judge()` 整个返回值（第四步 `evidence.hou_shape` 存的那份）。
  4d 读时去掉 `method`；`model_sha` 与第四步参数指纹 `hs` 段同算法（`hou_shape.fingerprint`），`methods_sha` 里是 `hou_shape=<指纹>`。
- 现役第四步只碰**已放行**、字是 候／𠋫 的非人裁格，只改字、不改放行；晚跑遍（`group_flow_hou_shape_late`，5c vis_ruling
  放行之后）判法同一个，只是补判主遍时还没放行、没 `evidence.hou_shape` 的格。3b 不知道放行，按 3a 候选触发（`trigger: cands`，
  登记表 hou 组是 侯俟候𠉀𠋫），给的是原样判法结论；哪些格用、主遍还是晚跑遍、改不改字，都留在 4d。
  3b 也会在 侯／俟 格上出分（方法只认 候／𠋫，那些分没意义），4d 不读这些格。
- 校准：`<模型去 .json>.calib.json`（给目录时 `calib.json`），`{"format": "near-calib/1", "knots": {"候": [[分…], [p…]]}}`，
  按 `sims.候` 映、𠋫＝1−p。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ._base import _dir_fingerprint, _load_calib


class HouShape:
    """候𠋫 书级刻形判法（`groups.hou_shape`，schema /1 几何量、/2 小网）包成 3b 方法，见模块头「hou_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import hou_shape
        self.model = hou_shape.load(str(self.path))
        self.chars = tuple(self.model.get("chars", ["候", "𠋫"]))
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`hou_shape.judge` 的结果 → `{候: q, 𠋫: 1−q}`（只用 judge 已取整的 p 或 v，不另跑模型）；都没有 → `{}`。"""
        hou, alt = self.chars
        if v.get("p") is not None:
            q = float(v["p"])
        elif v.get("v") is not None:
            lo, hi = float(self.model["lo"]), float(self.model["hi"])
            if hi - lo >= 1e-3:                 # v 已取 4 位：中间档够宽，取整挪不过 0.5
                z = math.log(9.0) * (lo + hi - 2.0 * float(v["v"])) / (hi - lo)
                q = round(1.0 / (1.0 + math.exp(-min(50.0, max(-50.0, z)))), 4)     # 截到 ±50：窄中间档时 exp 不溢出
            else:                               # 几乎没有中间档：按判出的字给分
                q = {hou: 1.0, alt: 0.0}.get(v.get("char"), 0.5)
        else:
            return {}
        return {hou: q, alt: round(1.0 - q, 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import hou_shape
        out = []
        for g in patches:
            v = hou_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "hou_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        hou, alt = self.chars
        kn = (self.calib or {}).get("knots", {}).get(hou)
        if not kn or hou not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[hou], xs, ys))
        return {hou: round(p, 4), alt: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `hs` 段同算法（`hou_shape.fingerprint`）。"""
        from .. import hou_shape
        return hou_shape.fingerprint(str(self.path))
