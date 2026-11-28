"""## flow_shape（注册字组的 5a.2 字形判法，3a `glyph_match.stages` 搬来，结构拆分 A4，2026-11-28）

包的是 `groups.shape_stage.judge`（3a `glyph_stages.stage_shape` 用的同一个函数：取注册表 `FLOW_GROUPS` 这一组 `FlowSpec.methods`
里 `needs_patch` 的方法——`rr_img`、`ids`、`zy_strokes`、HOG……——原样调，`MethodInput.ref／left／right` 一律空），吃 `char_patch`
字块图（3a 传的也是 char_patch）。一组一份，书配置写注册组 id：

    rr: {ref: rr, trigger: cands, methods: {flow_shape: {path: config/groups, group: rr}}}

`path` 只是占位（要存在，仓根 `config/groups` 即可），IDS 模板库等照 `ids_online.bank_path` 找（工作区 `config/groups/ids/<组>.json`
优先，其次仓里），同 3a。`cells[].candidates`（3a 候选）当 `MethodInput.cands` 传。

- `sims`：各方法给的字全一致（`why: agree`）→ `{该字: 1, 组内其余: 0}`；冲突、全弃权、缺图 → `{}`。
- `evidence`：`{method: "flow_shape", group, char, why, final, solvers}`，后五键与 3a `MatchRec.stage.shape[]` 一行同键同值
  （`solvers`＝[[方法名, 字, 置信度 4 位, why]…]；`final`＝`shape_stage.final(组)` 且给了字，只是「这组字形能单独定字」的标记，
  3b 不定字，放不放归第四步按 `handling.action`）。
- 指纹：`spec_fingerprint`＝组名＋本组字形方法名＋`ids_online.fingerprint([组])`（判法参数、模板库、覆盖表、IDS 总表），不含 `path`。
  代码 `shape_stage`、`methods`、`ids_online`、`registry` 在 glyph_near `code_deps` 里。
- 校准：没有（`calibrate` 一律 None），只当证据。
- 登记表：有字形方法的注册组（`shape_stage.inventory()` 的 final＋evidence，80 组）缺省 `handling.methods` 含 `flow_shape`；
  己已巳（jys）、日曰（ry）人定为 []，不跑。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


class FlowShape:
    """5a.2 字组看图判法（`groups.shape_stage`：注册组里只吃字块图的方法——量横、数横、宽高比、整字 HOG、IDS 部件……）
    包成 3b 方法（结构拆分 A4，2026-11-28），见模块头「flow_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path, group=None):
        from .. import shape_stage
        from ..flow import FlowConfig
        from ..registry import FLOW_GROUPS
        if group is None or str(group) not in FLOW_GROUPS:
            raise ValueError(f"flow_shape：要写 {{path: config/groups, group: 注册组 id}}，{group!r} 不是注册组")
        self.src, self.group = Path(path), str(group)
        self.methods = tuple(m.name for m in shape_stage.shape_methods(self.group))
        if not self.methods:
            raise ValueError(f"flow_shape：注册组 {self.group} 没有只吃字块图的方法（shape_stage.inventory 的 none 类）")
        self.members = tuple(sorted(FLOW_GROUPS[self.group].members))
        self._cfg = FlowConfig(groups=tuple(FLOW_GROUPS))

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import shape_stage
        cells = cells or [{} for _ in patches]
        out = []
        for g, c in zip(patches, cells):
            v = shape_stage.judge(self.group, str(c.get("id") or ""), list(c.get("candidates") or []), lambda _c, g=g: g, self._cfg)
            ev = {"method": "flow_shape", "group": self.group, "char": v.char, "why": v.why, "final": v.final,
                  "solvers": [[n, ch, round(float(cf), 4) if cf is not None else None, w] for n, ch, cf, w in v.solvers]}
            sims = {m: (1.0 if m == v.char else 0.0) for m in self.members} if v.char is not None else {}
            out.append({"sims": sims, "evidence": ev})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        return None

    @staticmethod
    def spec_fingerprint(d: Path, kw: dict) -> str:
        """组名＋这组的字形方法名＋IDS 模板库等（`ids_online.fingerprint`）的短哈希；`path` 不进（模板库按 ids_online 自己找）。"""
        from .. import ids_online, shape_stage
        g = str(kw.get("group"))
        h = hashlib.sha256()
        h.update(("group:" + g).encode())
        h.update(("|methods:" + ",".join(m.name for m in shape_stage.shape_methods(g))).encode())
        h.update(("|" + ids_online.fingerprint([g])).encode())
        return h.hexdigest()[:16]

    def fingerprint(self) -> str:
        return self.spec_fingerprint(self.src, {"group": self.group})

    @property
    def model_sha(self) -> str:
        return self.fingerprint()
