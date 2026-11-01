"""字组判法：每组一个**方法数组**（sheldon 2026-10-22 定）。

一个形近字组（两三个字）要解决，就是给它注册一个方法数组（`registry.FlowSpec.methods`）。数组里的方法依次试，
每个方法输出「放行」（给出组内一个字）或「待定」（`char=None`），带置信度（0–1）和留痕信息。
`combine="first"` 的组试到第一个放行就停；`combine="agree"` 的组每个方法都跑，给了字的必须一致（第二路当校验，
如日曰的宽高比、入人八的字形分类器、土士未末的量横、一二的数横）。合并、补放、复核、留证据都在 `flow.py`，本模块只管「一个方法怎么判一格」。

## 八类方法（`Method.kind`）

| kind | 是什么 | 实现 |
|---|---|---|
| `codepoint` | 码位归一：这套书在册配置 `codepoints:` 里定了用哪个码位，组内字一律给那个字（內内 別别 出岀 卷巻 晚晩，`registry.CODEPOINT_GROUPS`） | `Codepoint` |
| `freq` | 字频：殿本人裁只见一形（主形 ≥10 且 ≥2 册、其余 0）就给主形 | `Freq`（`freq.decide`） |
| `ctx_rule` | 文意 L1 固定搭配：前后各 20 字的词组／正则（`rules.yaml`），零模型 | `CtxRule`（`ctx_l1`） |
| `model` | 文意 L2 训练好的模型：SikuRoBERTa 目标位向量＋逻辑回归小头，按册留出定门槛 | `CtxModel`（`ctx_l2`） |
| `llm` | 文意 L3 大模型：大模型读过的格的答案表（只收 conf=high）；表里没有、L2 也给不出的格在线问（按窗口内容缓存，记 token） | `Llm`（`ctx_l3`）、`CtxOnline`（`ctx_llm`） |
| `hog` | 整字 HOG＋岭回归（二类或一对多） | `HogRidge`（`ids_whole`） |
| `ids` | IDS 部件：U-Net／折线／自动缝切开，部件模板最近邻（目前按组指定切法，`ids_online.SPECS`；将来做通用的） | `Ids`（`ids_online`） |
| `composite` | 复合：先用一个算子取局部（`Crop` 取框），再交给任意方法 | `Composite` |
| `custom` | 自定义：任意 python 函数，入参 `MethodInput`、出参 `GroupVerdict`（量横、一二数横、日曰宽高比、入人八字形分类器、库形最近） | `Custom` |

数组里也可以放一个子数组 `Chain`：里面的方法依次试、第一个放行的说了算，整体当一个方法
（文意 `ctx`＝L1 固定搭配 → L3 大模型答案表 → L2 模型 → L3 在线；表在前是因为表里读过的格有多家 strong 票，模型只补表里没有的格，
见 `CtxModel`；L3 在线只问前面都给不出字的格，见 `CtxOnline`）。

## 约定

- 方法只看 `MethodInput`（判别时就有的东西），**不看现行放行字**（见 `protocol` 模块头）；放行／待定与放行字怎么比由 `flow` 定。
- `name` 是留痕（`evidence.group.solvers[].solver`）里的名字，沿用 10-18 起的旧名（`ctx`／`ids`／`freq`…），产物证据不变；
  `kind` 是上面八类之一。
- 置信度：各方法自己的把握量（库 cov、判别值 margin、量横 |比值−1|…）截到 0–1；**跨方法不可比**，`flow` 不拿它做决定。
- 需要字块图的方法 `needs_patch=True`；字块按调用惰性取（每次调用都取一次，与旧 `_solve` 相同，缺图留痕次数不变）。
- 分层同 `groups` 包：只 import L0／L1；重的依赖（cv2、ids_online、rr_clf）在 `run` 里惰性 import。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import freq as _freq
from .protocol import GroupVerdict

KINDS = ("codepoint", "freq", "ctx_rule", "model", "llm", "hog", "ids", "composite", "custom")


@dataclass
class MethodInput:
    """一格交给方法判的全部输入（只读）。"""
    group: str                         # 组 id
    members: frozenset                 # 本步可给的字：组成员；两段判第二段时是族里的形
    cell_id: str
    cands: list                        # 库候选 [(字, cov)]，cov 降序
    ref: str | None                    # 整理本对位字（`ref_free` 组为 None）
    cfg: Any                           # `flow.FlowConfig`（字频表、L2 表、码位归一、门槛…）
    left: str | None = None            # 文意窗口（读序前文／后文）；只有组里有文意方法时才取
    right: str | None = None
    patch_fn: Callable[[str], Any] | None = None   # 格 id → 灰度字块（缺图 → None）
    cur: str | None = None             # 复核时格现放行的字（补放为 None）
    force_panel: bool = False          # 文意字不 strong 时一律交 L3 二审小组确认（`flow.decide` 在文意与字形冲突时重判用）

    def patch(self):
        return self.patch_fn(self.cell_id) if self.patch_fn is not None else None


def unit(x) -> float:
    """把方法自己的把握量截到 0–1（None → 0）。"""
    if x is None:
        return 0.0
    return min(1.0, max(0.0, float(x)))


def _out(v: GroupVerdict) -> GroupVerdict:
    v.conf = unit(v.conf)
    return v


@dataclass(frozen=True)
class Method:
    """方法基类。子类实现 `_run`；`run` 统一把置信度截到 0–1。"""
    name: str
    kind = "custom"
    needs_patch = False

    def run(self, inp: MethodInput) -> GroupVerdict:
        return _out(self._run(inp))

    def _run(self, inp: MethodInput) -> GroupVerdict:   # pragma: no cover - 抽象
        raise NotImplementedError


# —— 1 码位归一 ——

@dataclass(frozen=True)
class Codepoint(Method):
    """册配置 `codepoints:` 把组内某字映到组内另一个字（如 巻→卷）→ 给那个字，置信度 1；这套书没定 → 待定。
    库首位 cov 不到 `FlowConfig.codepoint_min_cov` 也待定（2026-10-26：褪墨页上库形 0.90 档对不上刻形）。"""
    name: str = "codepoint"
    kind = "codepoint"

    def _run(self, inp):
        canon = getattr(inp.cfg, "canon", None)
        if canon is None:
            return GroupVerdict(None, why="abstain:no_codepoints", via=self.name)
        c1 = max((v for _, v in inp.cands or ()), default=None)
        if c1 is not None and c1 < getattr(inp.cfg, "codepoint_min_cov", 0.0):
            return GroupVerdict(None, conf=c1, why="abstain:low_cov", via=self.name, extra={"cov": c1})
        targets = {canon(c) for c in inp.members} & set(inp.members)
        if len(targets) == 1 and any(canon(c) != c for c in inp.members):
            ch = next(iter(targets))
            return GroupVerdict(ch, conf=1.0, why="agree", via=self.name)
        return GroupVerdict(None, why="abstain:no_codepoint", via=self.name)


# —— 2 字频 ——

@dataclass(frozen=True)
class Freq(Method):
    name: str = "freq"
    kind = "freq"

    def _run(self, inp):
        c = inp.cfg
        v = _freq.decide(c.freq_table.get(inp.group), inp.members, c.freq_major,
                         c.freq_vols.get(inp.group), c.freq_min_vols)
        if v.char is not None:
            v.conf = 1.0
        return v


# —— 3 文意 L1 固定搭配、L2 训练模型、L3 大模型（合成子数组 `ctx`） ——

_L1: dict = {}
_L2: dict = {}      # L3 答案表（变量名沿用旧名）
_HEADS: dict = {}
_L3C: dict = {}                    # L3 在线答案缓存（路径 → `ctx_llm.AnswerCache`）


def _cell(inp: MethodInput):
    from .protocol import JudgeInput, window_from_text
    return JudgeInput(id=inp.cell_id, ref=inp.ref, window=window_from_text(inp.left or "", inp.right or ""))


def _spec(g: str):
    from .registry import FLOW_GROUPS
    return FLOW_GROUPS[g]


def _ctx_out(v: GroupVerdict) -> GroupVerdict:
    """文意类方法的留痕口径（沿用旧 `ctx` 解法）：via 记 `ctx:<后端>`，extra 只留命中的规则。"""
    keep = {k: v.extra[k] for k in ("rules", "ctx_drift", "other_conf", "strong", "runs", "p", "gap", "top",
                                     "llm_model", "llm_conf", "cached", "tok", "l2_top", "panel")
            if v.extra.get(k) not in (None, [], "")}
    return GroupVerdict(v.char, conf=v.conf, why=v.why, via=f"ctx:{v.via}" if v.via else "ctx", extra=keep)


@dataclass(frozen=True)
class CtxRule(Method):
    """`config/groups/<组>/rules.yaml` 的词组／正则，对整理本零冲突；命中给字（置信度 1），不命中待定。"""
    name: str = "ctx_rule"
    kind = "ctx_rule"

    def _run(self, inp):
        from .ctx_l1 import CtxL1Backend
        from .flow import rules_path
        g = inp.group
        if g not in _L1:
            _L1[g] = CtxL1Backend(rules_path(g), _spec(g).members)
        v = _L1[g].judge(_spec(g), _cell(inp))
        if v.char is not None:
            v.conf = 1.0
        return _ctx_out(v)


@dataclass(frozen=True)
class Llm(Method):
    """离线 haiku 答案表（`group_clf/1`，管线只查表）；这册没给表 → 不适用（`applies` 为假，子数组跳过它）。"""
    name: str = "llm"
    kind = "llm"
    after_pair: frozenset = frozenset()   # 前一字是这些字时不信表（己已巳：「嘉定己巳」的第二字，haiku 常读成「已」）

    def applies(self, inp) -> bool:
        return bool(inp.cfg.l2_tables.get(inp.group))

    def _run(self, inp):
        from .ctx_l3 import CtxL3Backend
        if self.after_pair and inp.left and inp.left[-1] in self.after_pair:
            return _ctx_out(GroupVerdict(None, why="abstain:pair", via="ctx_l3"))
        table = inp.cfg.l2_tables.get(inp.group)
        if table not in _L2:
            _L2[table] = CtxL3Backend(table)
        v = _L2[table].judge(_spec(inp.group), _cell(inp), inp.cfg.canon, getattr(inp.cfg, "l2_drift", 0))
        if v.char is not None:
            v.conf = 1.0          # 表里只收 conf=high
        return _ctx_out(v)


@dataclass(frozen=True)
class CtxModel(Method):
    """文意 L2：训练好的模型（`ctx_l2`，小头 `FlowConfig.l2_models[组]`）。这册没给小头 → 不适用。
    只补 L3 表里没有可用答案的格（前一步的 why 在 `FILLS` 里，或前面没有表）；表里大模型说「其他」、互相反对的格不补，留人审。"""
    name: str = "model"
    kind = "model"
    after_pair: frozenset = frozenset()   # 同 `Llm.after_pair`

    FILLS = frozenset({"cache_miss", "ctx_mismatch", "ver_mismatch", "abstain:new", "abstain:low_conf",
                       "abstain:missing_run", "abstain:empty", "abstain:ctx_l1"})

    def applies(self, inp) -> bool:
        return bool(getattr(inp.cfg, "l2_models", {}).get(inp.group))

    def _run(self, inp):
        from . import ctx_l2
        if self.after_pair and inp.left and inp.left[-1] in self.after_pair:
            return _ctx_out(GroupVerdict(None, why="abstain:pair", via="ctx_l2"))
        path = inp.cfg.l2_models[inp.group]
        if path not in _HEADS:
            _HEADS[path] = ctx_l2.load_head(path)
        return _ctx_out(ctx_l2.judge(_HEADS[path], inp.left or "", inp.right or "", inp.members))


def _panel_of(cfg, group: str) -> tuple:
    """本组用的 L3 二审小组（`FlowConfig.l3_panel`，只对 `l3_panel_groups` 里的组开）。"""
    return tuple(getattr(cfg, "l3_panel", ()) or ()) if group in (getattr(cfg, "l3_panel_groups", ()) or ()) else ()


@dataclass(frozen=True)
class CtxOnline(Method):
    """文意 L3 在线：管线里直接问大模型（`ctx_llm`，`FlowConfig.l3_online[组]` 给了提示词才适用）。
    只问前面各层都没给出字、也没有大模型读过下了结论的格（前一步的 why 在 `FILLS` 里）；L2 模型弃权时它的首选字记 `l2_top`，
    `FlowConfig.l3_need_l2_agree` 开时两者不同就弃权 `disagree:l2`。"""
    name: str = "llm_online"
    kind = "llm"
    after_pair: frozenset = frozenset()   # 同 `Llm.after_pair`

    FILLS = CtxModel.FILLS | frozenset({"abstain:low_p", "abstain:other_form", "abstain:right_only", "abstain:no_encoder"})

    def applies(self, inp) -> bool:
        return bool(getattr(inp.cfg, "l3_online", {}).get(inp.group))

    def run_after(self, inp, prev: GroupVerdict) -> GroupVerdict:
        from . import ctx_llm
        if self.after_pair and inp.left and inp.left[-1] in self.after_pair:
            return _ctx_out(GroupVerdict(None, why="abstain:pair", via="ctx_llm"))
        cfg = inp.cfg
        o = cfg.l3_online[inp.group]
        cache = o.get("rulings")            # 裁定库（seed_admit 给的 `RulingCache`）；缺省退本地 jsonl
        if cache is None:
            path = o.get("cache") or ""
            if path not in _L3C:
                _L3C[path] = ctx_llm.AnswerCache(path or None)
            cache = _L3C[path]
        v = ctx_llm.judge(inp.group, o["system"], o["ver"], inp.left or "", inp.right or "", inp.members,
                          model=cfg.l3_model, effort=cfg.l3_effort, cache=cache, cell=inp.cell_id,
                          panel=_panel_of(cfg, inp.group), ref=inp.ref)
        top = prev.extra.get("top")
        if top:
            v.extra["l2_top"] = top
            if v.char is not None and cfg.l3_need_l2_agree and v.char != top:
                v = GroupVerdict(None, why="disagree:l2", via=v.via, extra=v.extra)
        return _ctx_out(v)

    def _run(self, inp):
        return self.run_after(inp, GroupVerdict(None, why="abstain:empty"))


@dataclass(frozen=True)
class Chain(Method):
    """子数组：依次试，第一个放行的说了算；都待定 → 最后一个试过的方法的结论。不适用的方法（`applies` 为假）跳过。"""
    steps: tuple = ()
    kind = "chain"

    @property
    def needs_patch(self) -> bool:            # type: ignore[override]
        return any(s.needs_patch for s in self.steps)

    def _run(self, inp):
        v = GroupVerdict(None, why="abstain:empty", via=self.name)
        for s in self.steps:
            if hasattr(s, "applies") and not s.applies(inp):
                continue
            if isinstance(s, (CtxModel, CtxOnline)) and v.why not in type(s).FILLS:
                continue
            v = _out(s.run_after(inp, v)) if isinstance(s, CtxOnline) else s.run(inp)
            if v.char is not None:
                f = _spec(inp.group).flow
                if isinstance(s, CtxRule) and f.rule_strong and len(set(v.extra.get("rules") or ())) >= f.rule_strong:
                    v = GroupVerdict(v.char, conf=v.conf, why=v.why, via=v.via, extra={**v.extra, "strong": True})
                elif isinstance(s, CtxRule) and f.strong_over_ref:
                    v = self._confirm(v, inp)
                break
        if any(isinstance(s, CtxOnline) for s in self.steps):
            v = self._panel(v, inp)
        return v

    def _panel(self, v: GroupVerdict, inp) -> GroupVerdict:
        """L3 二审小组收尾（A24 2026-11-01，`ctx_llm.panel_verdict`）：前面各层的结论没有确认、又碰到分歧时，让几个强模型高 effort 独立读一遍。
        - 没给字（弃权）：小组全部同字 → 给字（strong）；全部说「其他」→ `abstain:other`（共字组接手）；其余照原样；
        - 给了字、还不 strong、与整理本或现放行字不同：小组同字 → strong；小组给了别的字 → 弃权 `disagree:panel`；其余照原样。
        己已巳 `after_pair`（干支第二字）、没密钥、已经问过小组的不再问。"""
        from . import ctx_llm
        cfg = inp.cfg
        panel = _panel_of(cfg, inp.group)
        o = (getattr(cfg, "l3_online", {}) or {}).get(inp.group)
        if (not panel or not o or v.extra.get("panel") or (v.extra.get("strong") and not inp.force_panel)
                or v.why in ("abstain:pair", "abstain:no_api_key")):
            return v
        norm = getattr(cfg, "canon", None) or (lambda c: c)
        if v.char is not None and not inp.force_panel:
            ref, cur = inp.ref, inp.cur
            if (not ref or norm(ref) == v.char) and (not cur or norm(cur) == v.char) or (not ref and not cur):
                return v
        cache = o.get("rulings")
        if cache is None:
            path = o.get("cache") or ""
            if path not in _L3C:
                _L3C[path] = ctx_llm.AnswerCache(path or None)
            cache = _L3C[path]
        pv = ctx_llm.panel_verdict(inp.group, o["system"], o["ver"], inp.left or "", inp.right or "", inp.members, panel,
                                    cache=cache, cell=inp.cell_id)
        pv2 = ctx_llm.panel_to_verdict(pv, {})
        if pv2 is None:
            return v if v.char is None else GroupVerdict(v.char, conf=v.conf, why=v.why, via=v.via,
                                                         extra={**v.extra, "panel": ctx_llm.panel_extra(pv, {})["panel"]})
        out = _ctx_out(pv2)
        if v.char is None:
            return out
        if out.char == v.char:
            return GroupVerdict(v.char, conf=v.conf, why=v.why, via=v.via, extra={**v.extra, "strong": True, "panel": out.extra["panel"]})
        return GroupVerdict(None, why="disagree:panel", via=v.via, extra={**v.extra, "panel": out.extra["panel"]})

    def _confirm(self, v: GroupVerdict, inp) -> GroupVerdict:
        """L1 规则给了字：组声明了 `strong_over_ref` 时再查 L2 表，表里同字且 strong → L1 的答案也记 strong（可改字）。
        规则单独不改字（vol34:101:1:11「四至八到曰疆域」`ry-ext-l1-日` 判反，表 strong 是曰）；规则与多遍都 high 的表
        一致才改（vol11 18:5:11、vol22 112:8:18「顧炎武日知錄」被 match_ref 放成曰，A24 10-26）。"""
        for s in self.steps:
            if isinstance(s, Llm) and s.applies(inp):
                t = s.run(inp)
                if t.char == v.char and t.extra.get("strong"):
                    return GroupVerdict(v.char, conf=v.conf, why=v.why, via=v.via, extra={**v.extra, "strong": True})
        return v


# —— 5 整字 HOG＋岭回归、6 IDS 部件、7 复合（取局部 → 方法） ——

def _ids_spec(g: str):
    from . import ids_online
    return ids_online.SPECS.get(g)


def _bank(g: str):
    from . import ids_online
    return ids_online.load_bank(ids_online.bank_path(g)) if ids_online.has_bank(g) else None


@dataclass(frozen=True)
class HogRidge(Method):
    """整字（或 `region` 指定的一块）HOG／像素特征 ＋ 岭回归；参数与模板库按组登记在 `ids_online.SPECS`／`config/groups/<组>/ids_bank.json`。
    判别值不到门槛、判成组外字（模板库里的陪衬类）、该类模板太少 → 待定。"""
    name: str = "ids"
    region: tuple | None = None               # None＝用 SPECS 里登记的；`Composite(Crop(..), HogRidge())` 会填它
    kind = "hog"
    needs_patch = True

    def _run(self, inp):
        from dataclasses import replace
        from . import ids_online
        g = inp.group
        if not ids_online.has_bank(g):
            return GroupVerdict(None, why="abstain:no_bank", via="ids")
        gray = inp.patch()
        if gray is None:
            return GroupVerdict(None, why="abstain:no_patch", via="ids")
        spec = _ids_spec(g)
        if self.region is not None:
            spec = replace(spec, region=tuple(self.region))
        return ids_online._judge_whole(gray, _bank(g), spec, _spec(g).members)


@dataclass(frozen=True)
class Ids(Method):
    """IDS 部件：按组登记的切法（U-Net 左右／上中下、折线、自动缝）切开，部件模板最近邻，margin 不够待定。
    目前没有通用的「字块 → IDS」函数，切法按组指定（`ids_online.SPECS`）；没登记模板库的组一律待定（`abstain:no_bank`），不取图。"""
    name: str = "ids"
    kind = "ids"
    needs_patch = True

    def _run(self, inp):
        from . import ids_online
        if not ids_online.has_bank(inp.group):
            return GroupVerdict(None, why="abstain:no_bank", via="ids")
        return ids_online.judge(inp.group, inp.patch())


@dataclass(frozen=True)
class Crop:
    """取局部算子：归一字块里占宽高 (x0, x1, y0, y1) 的一块。"""
    region: tuple


@dataclass(frozen=True)
class Composite(Method):
    """复合：先用算子取局部（目前只有 `Crop`；U-Net 切段待 IDS 通用化后拆出来），再交给内层方法判。"""
    op: Any = None
    inner: Method | None = None
    kind = "composite"

    @property
    def needs_patch(self) -> bool:            # type: ignore[override]
        return True

    def _run(self, inp):
        from dataclasses import replace
        if isinstance(self.op, Crop) and isinstance(self.inner, HogRidge):
            return replace(self.inner, region=tuple(self.op.region)).run(inp)
        raise ValueError(f"composite：算子 {self.op!r} 与内层方法 {self.inner!r} 的组合还不支持")


@dataclass(frozen=True)
class Only(Method):
    """限定入口再跑内层方法：库分差内（`cfg.delta`）的候选与整理本字都落在 `chars` 里才跑，否则待定（`abstain:gate`）；
    内层给的字不在 `give` 里也待定（`abstain:gate_give`）。组扩了成员、而旧判法只在原来那几个字之间验证过时用
    （于千子干：子于整字 HOG 只认 子于干、只验证过给 子于，碰到 千 会硬判，2026-10-24 A24）。"""
    inner: Method | None = None
    chars: frozenset = frozenset()
    give: frozenset = frozenset()
    kind = "composite"

    @property
    def needs_patch(self) -> bool:            # type: ignore[override]
        return self.inner.needs_patch

    def _run(self, inp):
        c1 = inp.cands[0][1] if inp.cands else 0.0
        close = {c for c, v in (inp.cands or []) if c1 - v < inp.cfg.delta}
        if not close or close - self.chars or (inp.ref and inp.ref not in self.chars):
            return GroupVerdict(None, why="abstain:gate", via=self.name)
        v = self.inner.run(inp)
        if v.char is not None and v.char not in self.give:
            return GroupVerdict(None, conf=v.conf, why="abstain:gate_give", via=v.via, extra=v.extra)
        return v


# —— 8 自定义函数 ——

@dataclass(frozen=True)
class Custom(Method):
    """任意 python 函数 `fn(MethodInput) -> GroupVerdict`。`patch=True` 时先取字块，取不到就待定（`abstain:no_patch`），不调函数。"""
    fn: Callable | None = None
    patch: bool = False
    kind = "custom"

    @property
    def needs_patch(self) -> bool:            # type: ignore[override]
        return self.patch

    def _run(self, inp):
        if self.patch:
            img = inp.patch()
            if img is None:
                return GroupVerdict(None, why="abstain:no_patch", via=self.name)
            return self.fn(inp, img)
        return self.fn(inp)


def top1(inp: MethodInput) -> GroupVerdict:
    """库形最近：库首位 cov ≥ `top1_cov` 且在组里 → 给它。"""
    if not inp.cands:
        return GroupVerdict(None, why="abstain:no_cands", via="top1")
    top, c1 = inp.cands[0]
    if c1 >= inp.cfg.top1_cov and top in inp.members:
        return GroupVerdict(top, conf=c1, why="agree", via="top1", extra={"cov": c1})
    return GroupVerdict(None, conf=c1, why="abstain:low_cov", via="top1", extra={"cov": c1})


def form_top1(inp: MethodInput) -> GroupVerdict:
    """两段判第二段的库形最近：族内最高分的形，cov ≥ `min_cov`，且领先族内其他形 ≥ `form_margin`。"""
    inf = [(c, s) for c, s in (inp.cands or []) if c in inp.members]
    if not inf:
        return GroupVerdict(None, why="abstain:no_cands", via="top1")
    best, s1 = inf[0]
    if s1 < inp.cfg.min_cov:
        return GroupVerdict(None, conf=s1, why="abstain:low_cov", via="top1", extra={"cov": s1})
    if len(inf) > 1 and s1 - inf[1][1] < inp.cfg.form_margin:
        return GroupVerdict(None, conf=s1, why="abstain:form_close", via="top1",
                            extra={"cov": s1, "gap": round(s1 - inf[1][1], 4)})
    return GroupVerdict(best, conf=s1, why="agree", via="top1", extra={"cov": s1})


def bars(inp: MethodInput, img) -> GroupVerdict:
    """量横（土士、未末）：下横／上横 > 1 给下横长的字，< 1 给上横长的字，离 1 不足 0.1 待定。见 `bars.py`。"""
    from .bars import BarsImageBackend
    from .protocol import JudgeInput, window_from_text
    v = BarsImageBackend().judge(_spec(inp.group), JudgeInput(id=inp.cell_id, ref=inp.ref, window=window_from_text("", ""),
                                                             patch=lambda: img))
    return GroupVerdict(v.char, conf=v.conf, why=v.why, via="bars", extra={"ratio": v.extra.get("ratio")})


def yr_bars(inp: MethodInput, img) -> GroupVerdict:
    """一二数横（`bars.count_bars`）：一横给「一」，两横（上短下长）给「二」，残笔、噪点、边框线弃权。"""
    from .bars import count_bars
    ch, why = count_bars(img)
    ok = ch in inp.members
    return GroupVerdict(ch if ok else None, conf=1.0 if ok else 0.0, why="agree" if ok else f"abstain:{why}", via="yr_bars")


def rr_img(inp: MethodInput, img) -> GroupVerdict:
    """入人八字形分类器（`utils.rr_clf`，随机森林）：只验证过降审，补放要靠 `lift_needs` 拦。"""
    from ..utils import rr_clf
    c = rr_clf.classify(img, inp.cfg.rr_model or None, inp.cfg.rr_p)
    pick = c.get("pick")
    ok = pick in inp.members
    return GroupVerdict(pick if ok else None, conf=c.get("p"), why="agree" if ok else "abstain:rr_clf", via="rr_img",
                        extra={"probs": c.get("probs")})


def ry_shape(inp: MethodInput, img) -> GroupVerdict:
    """日曰宽高比（`aspect.py`）：日窄曰宽，只当第二路。置信度＝离弃权带的远近。"""
    from . import aspect
    ch, ratio = aspect.judge(img)
    ok = ch in inp.members
    conf = None if ratio is None else (aspect.LOW - ratio if ch == "日" else ratio - aspect.HIGH if ch == "曰" else 0.0) * 5
    return GroupVerdict(ch if ok else None, conf=conf if ok else 0.0, why="agree" if ok else "abstain:aspect",
                        via="ry_shape", extra={"ratio": None if ratio is None else round(float(ratio), 3)})


# —— 常用方法与数组（registry 用） ——

FREQ = Freq()
CTX = Chain("ctx", steps=(CtxRule(), Llm(), CtxModel(), CtxOnline()))
#: 己已巳的文意：两个族字相连（干支「己巳」）时第二字不查表，规则判不了就待定（vol06:125:6:8「嘉定己巳書成」表里是「已」）
JYS_CTX = Chain("ctx", steps=(CtxRule(), Llm(after_pair=frozenset("己已巳")), CtxModel(after_pair=frozenset("己已巳")),
                                 CtxOnline(after_pair=frozenset("己已巳"))))
TOP1 = Custom("top1", fn=top1)
FORM_TOP1 = Custom("top1", fn=form_top1)
BARS = Custom("bars", fn=bars, patch=True)
RR_IMG = Custom("rr_img", fn=rr_img, patch=True)
RY_SHAPE = Custom("ry_shape", fn=ry_shape, patch=True)
YR_BARS = Custom("yr_bars", fn=yr_bars, patch=True)
IDS = Ids()
HOG = HogRidge()
CODEPOINT = Codepoint()


def hog_or_crop(region: tuple | None) -> Method:
    """整字 HOG；登记了取框（不是整字）就包成「取框 → HOG」的复合方法。名字都是 `ids`（留痕沿用旧名）。"""
    if region is None or tuple(region) == (0.0, 1.0, 0.0, 1.0):
        return HogRidge()
    return Composite("ids", op=Crop(tuple(region)), inner=HogRidge())


def describe(m: Method) -> str:
    """人读的一行：方法类（自定义函数带名字），子数组展开。"""
    if isinstance(m, Chain):
        return "[" + " → ".join(describe(s) for s in m.steps) + "]"
    if isinstance(m, Composite):
        return f"composite(crop{tuple(m.op.region)} → {describe(m.inner)})"
    if isinstance(m, Only):
        return f"only({''.join(sorted(m.chars))} → {describe(m.inner)} → {''.join(sorted(m.give))})"
    if isinstance(m, CtxOnline):
        return "llm_online"
    return f"custom:{m.name}" if m.kind == "custom" else m.kind
