"""## pair_shape（两字刻形二选一：史记 之矣 /1、全唐文 大太／王玉／還遺 /2，第四步 group_flow 的书级判法搬来，2026-11-28）

包的是 `groups.pair_shape.judge`（seed_admit `_pair_shape_pass` 用的同一个函数），吃 `char_patch` 字块图。模型是第四步那份书级文件，
**一对一个文件**（数据目录 `config/groups/pair_shape_<拼音>.json`；`group_flow_pair_shape` 单个，`group_flow_pair_shapes` 是 `{两字: 文件}`
可挂多对），两种 schema：`pair_shape/1`（48px HOG＋PCA 近邻组外护栏＋逻辑回归）、`pair_shape/2`（主笔画紧框墨量图＋逻辑回归，
组外判别 `other` 或多类 `multi`）。书配置照 part_shape 写 `{path, pair}`（`pair` 只用来核对是不是这个文件的两个字、并进指纹），
每对开一个组（登记表组 `dt` 大太、`wyu` 王玉、`yh` 還遺；之矣 是 11-28 为此补进登记表的 `p:之矣`）：

    dt: {ref: dt, trigger: cands, methods: {pair_shape: {path: config/groups/pair_shape_dt.json, pair: [大, 太]}}}
    zy: {ref: "p:之矣", trigger: cands, methods: {pair_shape: {path: config/groups/pair_shape_zhiyi.json, pair: [之, 矣]}}}

- `sims`：同 rr_shape，用 `judge` 给的决策值 s（已取 3 位，`score>0` 给 chars[1]）：`{chars[1]: σ(s), chars[0]: 1−σ(s)}`（各取 4 位；
  多类模型的 s＝log p(chars[1]) − log p(chars[0])，σ(s) 就是只看这两类时 chars[1] 的概率）。没算出 s 的弃权（无墨、/1 的近邻组外护栏、
  NaN）→ `{}`；算出了 s 的弃权（分差不够、/2 的组外判别或多类最像组外字）仍给 sims，弃权记在证据里。**`other`／`margin`／`top`
  只进证据、不进 sims**。
- `evidence`：`{method: "pair_shape", **judge()}`，即 `char, why` 加 `nn`（/1）、`score`、`other`（/2 组外判别）、`margin`／`top`（/2 多类），
  judge 出了哪几个键就是哪几个，与第四步 `evidence.pair_shape`（`_pair_shape_pass` 的 trail）逐键同值。4d 读时去掉 `method`；
  第四步另加的 `nm_5b`（护栏 never_match 格的 5-b 首位）是 4d 的事，3b 不出。
- **只搬判法**：现役第四步的触发（库首位或整理本字在这一对里、整理本是第三个字不判、字组流程已给字不越过）、`veto`（已放行格
  |s|≥`veto_thr` 降审，`group_flow_pair_shape_veto`）、`nm_5b`、坐标对位全部留在 4d。3b 用 `trigger: cands` 罩住
  （3a 首位或前 topk 名里有这两字之一就跑），多跑的格 4d 不读。
- 指纹：`method_fingerprint("pair_shape", {path, pair})`，同 part_shape（文件＋同名校准表的指纹并上 pair，按码位排）；`methods_sha`
  里是 `<组>:pair_shape=<指纹>`。4d 用书级参数里那个文件和它的 `chars` 调同一个函数比对。`model_sha`＝`pair_shape.fingerprint(文件)`，
  与第四步参数指纹 `ps`／`pp` 段里每个文件的那段同算法。
- 校准：`<去 .json>.calib.json`，`{"format": "near-calib/1", "knots": {chars[1]: [[σ(s)…], [p…]]}}`。**现在没有校准表**（收尾不出 p）。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ._base import _dir_fingerprint, _load_calib, _pair_fingerprint


class PairShape:
    """两字刻形二选一（`groups.pair_shape`，schema /1 HOG、/2 墨量图）包成 3b 方法，见模块头「pair_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path, pair=None):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import pair_shape
        self.model = pair_shape.load(str(self.path))
        self.chars = tuple(self.model["chars"])
        self.want = None if pair is None else [str(c) for c in pair]
        if self.want is not None and sorted(self.want) != sorted(self.chars):
            raise ValueError(f"pair_shape：{self.path} 是 {''.join(self.chars)} 的模型，书配置写的 pair 是 {''.join(self.want)}")
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`pair_shape.judge` 的结果 → `{chars[1]: σ(s), chars[0]: 1−σ(s)}`（s 用 judge 已取整的 score）；没有 s → `{}`。"""
        s = v.get("score")
        if s is None:
            return {}
        a, b = self.chars
        q = round(1.0 / (1.0 + math.exp(-min(50.0, max(-50.0, float(s))))), 4)    # 截到 ±50：多类的对数概率差可能很大
        return {b: q, a: round(1.0 - q, 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import pair_shape
        out = []
        for g in patches:
            v = pair_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "pair_shape", **v}})
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
        """模型文件的版本，与第四步参数指纹里 `ps`／`pp` 段同算法（`pair_shape.fingerprint`）。"""
        from .. import pair_shape
        return pair_shape.fingerprint(str(self.path))
