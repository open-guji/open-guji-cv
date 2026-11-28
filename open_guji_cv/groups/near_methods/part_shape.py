"""## part_shape（剌刺／疎踈／攢攅 等差在一块部件的字对，第四步 group_flow 的书级部件刻形判法搬来，2026-11-28）

包的是 `groups.part_shape.judge`（seed_admit `_part_shape_pass` 用的同一个函数，按这一对的部件框 `box` 截部件、同一组网），
吃 `char_patch` 字块图。模型是第四步那份书级文件（数据目录 `config/groups/part_shape.json`，`schema: part_shape/1`，**一份挂多对**），
所以书配置要写明是哪一对：

    ci: {ref: ci, trigger: cands, methods: {part_shape: {path: config/groups/part_shape.json, pair: [剌, 刺]}}}

`pair` 两个字须是模型里某一对的两个字（次序不论，sims 的方向按模型里的 `chars`）；文件里只有一对时可以只写路径字符串。
一个组挂一对；一份文件里的几对要各开一个组（各自的 `ref`）。

- `sims`：`{chars[1]: p, chars[0]: 1−p}`（p＝`judge` 给的 chars[1] 概率，已取 4 位，同第四步 `evidence.part_shape.p`），同 wu_shape；
  取不出部件（`abstain:no_ink`）→ `{}`；门槛中间（`abstain:low_p`）仍给 sims。
- `evidence`：`{method: "part_shape", char, why, p, pair}`，后几键＝`judge()` 整个返回值（第四步 `evidence.part_shape` 存的那份，
  `pair` 是两字拼起来，如 `剌刺`）。4d 读时去掉 `method`。
- 指纹：`method_fingerprint("part_shape", {path, pair})`＝`part_shape=<模型文件（＋同名校准表）指纹与 pair（按码位排）合起来的短哈希>`，
  `methods_sha` 里是 `<组>:part_shape=<指纹>`；4d 用 `group_flow_part_shape` 和本格所在那一对（`part_shape.pair_of(model, 字)["chars"]`）
  调同一个函数比对。`model_sha`＝`part_shape.fingerprint(模型文件)`，与第四步参数指纹 `pt` 段同算法。
- 现役第四步只判**本格字（库首位）落在某一对里**的格；3b 用 `trigger: cands` 罩住。登记表里 剌刺 是注册组 `ci`，
  疎踈、攢攅 是单立字对 `p:疎踈`、`p:攅攢`。
- 校准：模型文件旁边 `<去 .json>.calib.json`，`{"format": "near-calib/1", "knots": {chars[1]: [[p…], [校准 p…]]}}`，
  按字取，几对共用一份表也行。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ._base import _dir_fingerprint, _load_calib, _pair_fingerprint


class PartShape:
    """剌刺／疎踈 等部件刻形判法（`groups.part_shape`，一份模型挂多对）包成 3b 方法，取其中一对，见模块头「part_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path, pair=None):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import part_shape
        model = part_shape.load(str(self.path))
        if pair is None:
            if len(model["pairs"]) != 1:
                raise ValueError(f"part_shape：{self.path} 挂了 {len(model['pairs'])} 对，书配置要写 "
                                 f"{{path, pair: [字, 字]}} 指明哪一对")
            self.pair = model["pairs"][0]
            self.want = None
        else:
            want = [str(c) for c in pair]
            hit = [pr for pr in model["pairs"] if sorted(pr["chars"]) == sorted(want)]
            if len(want) != 2 or not hit:
                raise ValueError(f"part_shape：{self.path} 里没有 {''.join(want)} 这一对"
                                 f"（有 {[''.join(pr['chars']) for pr in model['pairs']]}）")
            self.pair = hit[0]
            self.want = want
        self.chars = tuple(self.pair["chars"])
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`part_shape.judge` 的结果 → `{chars[1]: p, chars[0]: 1−p}`（p 用 judge 已取整的那个值）；没有 p → `{}`。"""
        q = v.get("p")
        if q is None:
            return {}
        a, b = self.chars
        return {b: float(q), a: round(1.0 - float(q), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import part_shape
        out = []
        for g in patches:
            v = part_shape.judge(g, self.pair)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "part_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        a, b = self.chars
        kn = (self.calib or {}).get("knots", {}).get(b)
        if not kn or b not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[b], xs, ys))
        return {b: round(p, 4), a: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src) if self.want is None else _pair_fingerprint(self.src, self.want)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `pt` 段同算法（`part_shape.fingerprint`）。"""
        from .. import part_shape
        return part_shape.fingerprint(str(self.path))
