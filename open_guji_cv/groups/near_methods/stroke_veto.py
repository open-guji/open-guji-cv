"""## stroke_veto（己／已巳、千／干 笔画反向护栏，第四步 `_stroke_veto_pass` 的看图判法搬来，2026-11-28）

包的是 `groups.stroke_veto.judge`（seed_admit `_stroke_veto_pass` 用的同一个函数：通用模板配准、量「接不接」的笔画特征、
类统计似然比判），吃 `char_patch` 字块图。模型是第四步那份书级文件（数据目录 `config/groups/stroke_veto.json`，`schema: stroke_veto/1`，
**一份挂几组**：`jys` 己 对 已巳、`qg` 千 对 干），书配置写明是哪一组（`group`＝模型里的组名），3b 组键就用模型组名：

    jys: {ref: jys, trigger: cands, methods: {stroke_veto: {path: config/groups/stroke_veto.json, group: jys}}}
    qg:  {ref: zy, chars: [千, 干], trigger: cands, methods: {stroke_veto: {path: config/groups/stroke_veto.json, group: qg}}}

登记表：`jys`（己已巳，注册组，near）原样对上；千干 在注册组 `zy`（于千子干）里，`ref: zy` 再用 `chars: [千, 干]` 盖掉成员
（于、子 是极常见字，不盖的话凡候选里有 于／子 的格都要配准一次，4d 一格不读）。文件里只有一组时可以只写路径字符串。
**2026-11-28 起登记表 jys 的 `handling.methods` 为 []**（Sheldon 11-27：己已巳只做文意、不做字形区分），书配置照上面写 jys 那行会被
3b 警告、跳过（`near_registry.resolve`，计入 `PageNear.skipped_methods`）；方法本身仍认模型里的 jys 组，只是 3b 不再给它跑。

- 判法：现役 `judge(图, 组)` → `{x, cls, why, llr}`：`cls` 是**类名**（`classes` 把字映到类，jys 的 已／巳 本书刻法相同并成一类 `已巳`）；
  似然比领先量 `llr`（2 位）≥ `t` 才给类，`why: llr`；不够 → `abstain`（有 `llr`）；离两类都远（`max_z`）→ `out`（无 `llr`）；
  贴坏、无墨 → `bad_fit`（只有 `cls`／`why`）。
- `sims`：只认两类的组（`build` 出的都是两类；别的报错）。`llr` 是两类对数似然差，σ(llr) 就是等先验下领先那一类的概率：
  领先类的字各给 `σ(llr)`、另一类的字各给 `1−σ(llr)`（4 位，llr 用 judge 已取 2 位的那个）。判出了类 → 领先类＝`cls`，
  所以最高分的字总是现役判出的类（t ≥ 0 时 σ(llr) ≥ σ(t)）；`abstain` 时 judge 不出方向，3b 拿同一张图再量一遍特征
  （`stroke_veto.features`，确定性，同一个值）按对数似然定领先类，分在 [0.5, σ(t)) 之间；`out`／`bad_fit` 没有 llr → `{}`。
  jys 的 已、巳 同分（方法分不开这两个字，**不是**说它们是同一个字：登记表里 己已巳 仍是三个字、type near）。
- `evidence`：`{method: "stroke_veto", group: 模型组名, **judge()}`，后几键＝`judge()` 整个返回值（同键同值同舍入）。
  第四步降审时写进 `evidence.stroke_veto` 的是 `{group, cls, llr, x}`（llr／x 缺则 None），`stroke_veto_trail(证据)` 由 3b 证据得出与它
  逐键相等的那份；判不判降审（`cls` 非空且≠放行字的类）、`channels` 过滤、人裁格不碰，都留在 4d。
- 触发：现役只看**已放行**、放行字在模型某组里（且通道在 `channels` 里）的格，3b 看不到放行，用 `trigger: cands` 罩（3a 首位或前 topk
  名里有组内字就跑）。罩不住的格：放行字被前面的通道改成了 3a 首位与前 topk 名之外的字（整理本对位放行、字组流程、刻形判法改字等），
  和备选切法列——4d 本地现算并计数。多跑的格（没放行、通道不在 `channels`）4d 不读。
- 指纹：`method_fingerprint("stroke_veto", {path, group})`＝模型文件（＋同名校准表）指纹与组名合起来的短哈希，`methods_sha` 里是
  `<组>:stroke_veto=<指纹>`；4d 用 `SeedAdmitParams.stroke_veto`（已解析成绝对路径）和 `stroke_veto.group_of(模型, 放行字)` 的组名调
  同一个函数比对。`model_sha`＝`stroke_veto.fingerprint(模型文件)`，与第四步参数指纹 `stroke_veto_fingerprint` 同值。
- 校准：`<去 .json>.calib.json`，`{"format": "near-calib/1", "knots": {字: [[σ(llr)…], [p…]]}}`，按该字的分映 p、另一类＝1−p。
  只在两类都是单字时出 p（qg）；jys 的 已巳 是合类，组内各字的 p 分不开，`calibrate` 一律 None（只当证据，不把 已、巳 归一）。
  **现在没有校准表**（收尾不出 p）。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ._base import _dir_fingerprint, _load_calib, _group_fingerprint


STROKE_VETO_KEYS = ("group", "cls", "llr", "x")


def stroke_veto_trail(ev: dict) -> dict:
    """3b stroke_veto 证据（`{method, group, **judge()}`）→ 第四步降审时写进 `evidence.stroke_veto` 的那份
    `{group, cls, llr, x}`（llr／x 缺则 None，同现役 `v.get`），逐键相等。只搬字段，不判降不降。"""
    return {k: ev.get(k) for k in STROKE_VETO_KEYS}


class StrokeVeto:
    """笔画反向护栏的看图判法（`groups.stroke_veto`，一份模型挂几组）包成 3b 方法，取其中一组，见模块头「stroke_veto」。"""

    patch = "char_patch"

    def __init__(self, path: Path, group=None):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import stroke_veto
        model = stroke_veto.load(str(self.path))
        groups = model["groups"]
        if group is None:
            if len(groups) != 1:
                raise ValueError(f"stroke_veto：{self.path} 挂了 {len(groups)} 组 {sorted(groups)}，书配置要写 "
                                 f"{{path, group: 组名}} 指明哪一组")
            self.group = next(iter(groups))
            self.want = None
        else:
            if str(group) not in groups:
                raise ValueError(f"stroke_veto：{self.path} 里没有组 {group!r}（有 {sorted(groups)}）")
            self.group = self.want = str(group)
        self.gm = groups[self.group]
        cls_order = list(dict.fromkeys(self.gm["classes"].values()))
        if len(cls_order) != 2:
            raise ValueError(f"stroke_veto：{self.path} 组 {self.group} 有 {len(cls_order)} 类 {cls_order}，3b 方法只认两类的组")
        self.classes: tuple[str, str] = (cls_order[0], cls_order[1])
        self.members = {c: [ch for ch, k in self.gm["classes"].items() if k == c] for c in self.classes}
        self.calib = _load_calib(p)

    def lead_class(self, g: np.ndarray, v: dict) -> str | None:
        """领先的类：判出了类就是 `cls`；似然比不够（`abstain`）时 judge 不给方向，拿同一张图再量一遍特征按对数似然定
        （`llr_decide` 的次序，同分取前者）；没有 llr（`out`／`bad_fit`）→ None。"""
        if v.get("llr") is None:
            return None
        if v.get("cls") is not None:
            return v["cls"]
        from .. import stroke_veto
        x, _bad = stroke_veto.features(g, self.gm)
        if x is None:                   # 不会发生（judge 刚量出过同一张图），防字块被改
            return None
        ll = self.gm["_stats"].loglik(x)
        return sorted(ll, key=ll.get, reverse=True)[0]

    def sims_of(self, v: dict, lead: str | None) -> dict[str, float]:
        """`judge` 的结果＋领先类 → 领先类的字各 σ(llr)、另一类的字各 1−σ(llr)（4 位；llr 用 judge 已取 2 位的那个）；没有 → `{}`。"""
        if lead is None or v.get("llr") is None:
            return {}
        q = round(1.0 / (1.0 + math.exp(-min(50.0, max(-50.0, float(v["llr"]))))), 4)
        other = self.classes[1] if lead == self.classes[0] else self.classes[0]
        out = {ch: q for ch in self.members[lead]}
        out.update({ch: round(1.0 - q, 4) for ch in self.members[other]})
        return out

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .. import stroke_veto
        out = []
        for g in patches:
            v = stroke_veto.judge(g, self.gm)
            out.append({"sims": self.sims_of(v, self.lead_class(g, v)),
                        "evidence": {"method": "stroke_veto", "group": self.group, **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        """两类都是单字（qg）才出 p；有合类（jys 的 已巳）时各字的 p 分不开 → None（不把异义形近字归一）。"""
        if any(len(v) != 1 for v in self.members.values()):
            return None
        (a,), (b,) = self.members[self.classes[0]], self.members[self.classes[1]]
        knots = (self.calib or {}).get("knots") or {}
        pos = next((c for c in (a, b) if c in knots), None)
        if pos is None or pos not in sims:
            return None
        xs, ys = knots[pos]
        p = float(np.interp(sims[pos], xs, ys))
        neg = b if pos == a else a
        return {pos: round(p, 4), neg: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src) if self.want is None else _group_fingerprint(self.src, self.want)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹 `stroke_veto_fingerprint` 同算法（`stroke_veto.fingerprint`）。"""
        from .. import stroke_veto
        return stroke_veto.fingerprint(str(self.path))
