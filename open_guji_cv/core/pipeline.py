"""Pipeline：按版面选的 DAG，来自 pipelines/<id>.yaml。

边由 consumes / produces 推出；yaml 里的 steps 顺序必须是一个合法拓扑序
（上游在前），加载时校验，不自动重排——顺序本身是人写给人看的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .step import STEPS, Step

PIPELINES_DIR = Path(__file__).resolve().parent.parent / "pipelines"


def _produces(step: Step) -> set[str]:
    """一个 Step 实际能产出的种类集合，含它出口挂的闸产出的种类。

    闸自己是正常注册进 `STEPS` 的 Step（有自己的 `produces`），这里只是在算拓扑时
    把它记到被挂的 Step 头上——闸不出现在 yaml 的 `steps:` 里，但它产出的东西
    （如 `gate_manifest`）下游 Step 仍然要能在 `Pipeline.validate()`/`upstream()`
    里查到是谁「提供」的，否则移走闸这一个节点会让下游看起来断了链。"""
    out = set(step.spec.produces)
    if step.spec.gate:
        out |= set(STEPS[step.spec.gate.id].spec.produces)
    return out


@dataclass
class Pipeline:
    id: str
    title: str
    steps: list[str]
    selector: dict = field(default_factory=dict)
    needs: dict[str, list[str]] = field(default_factory=dict)   # 显式补充的边
    notes: str = ""
    #: yaml 的 `params:` 段——**这条管线下**各 Step（含闸）的默认参数覆盖
    #: `{step_id: {字段: 值}}`（2026-09-14 加，三模式方案「地基 1」）。同一份 Step 代码在
    #: 刻本链与现代链里默认参数不同，差异写在这里而不是分叉代码；CLI `--params` /
    #: 控制台的覆盖仍然优先于它（见 `Engine.__init__`）。
    params: dict[str, dict] = field(default_factory=dict)

    # ── 图 ───────────────────────────────────────────────────────────
    def step(self, sid: str) -> Step:
        return STEPS[sid]

    def producer_of(self, kind_id: str) -> Step:
        """**本管线里**产出 `kind_id` 的 Step（含各 Step 出口挂的闸）；本管线没有再退回
        全局注册表（`core.step.producer_of`）。

        2026-09-14 加（三模式方案「地基 2」）：同一种产物可以有多个产出者——刻本链
        `border_detect` 与现代链 `line_detect` 都产 `borders`，各自的闸都产
        `border_detect_gate_manifest`。全局注册表按注册顺序取第一个，会让现代链读到
        刻本 Step 的产物目录；查产物必须按当前管线来。"""
        for sid in self.steps:
            s = STEPS[sid]
            if kind_id in s.spec.produces:
                return s
            if s.spec.gate and kind_id in STEPS[s.spec.gate.id].spec.produces:
                return STEPS[s.spec.gate.id]
        from .step import producer_of as _global
        return _global(kind_id)

    def upstream(self, sid: str) -> list[str]:
        """直接上游：产出本步 consumes / optional_consumes 的那些步（含它们出口挂的
        闸产出的）+ needs 里显式写的。

        **可选上游也算图上的边**——硬/可选的区别只在"缺席时阻不阻塞"（见
        `StepSpec.optional_consumes`），拓扑序与过期传播两件事上两者一样：
        `rare_candidates` 重跑了（开关开着时），`align_ref` 那一页照样该标 stale。
        """
        me = STEPS[sid]
        wants = (*me.spec.consumes, *me.spec.optional_consumes)
        ups: list[str] = []
        for other in self.steps:
            if other == sid:
                break
            o = STEPS[other]
            if any(k in _produces(o) for k in wants) or other in self.needs.get(sid, []):
                ups.append(other)
        return ups

    def downstream(self, sid: str) -> list[str]:
        return [s for s in self.steps if sid in self.upstream(s)]

    def descendants(self, sid: str) -> list[str]:
        seen: list[str] = []
        stack = [sid]
        while stack:
            cur = stack.pop()
            for d in self.downstream(cur):
                if d not in seen:
                    seen.append(d)
                    stack.append(d)
        return [s for s in self.steps if s in seen]

    def _gate_host(self, gate_id: str) -> str | None:
        """`gate_id` 是不是挂在本 pipeline 某个步骤出口的闸；是则返回那个步骤的 id。

        闸（`attach_gate` 挂的那种）不出现在 yaml 的 `steps:` 里、也不在
        `self.steps` 中——它跟着被挂的那个 Step 自动跑（见 `Engine.run`）。
        """
        for sid in self.steps:
            g = STEPS[sid].spec.gate
            if g and g.id == gate_id:
                return sid
        return None

    def _index(self, sid: str | None) -> int | None:
        # 空字符串按「不设限」处理，同 None——表单/查询串里留空传的是
        # `''` 不是 `null`，两者混过来都该是「不设下限/上限」（2026-09-09
        # 控制台「跑这批」实锤：前端漏转，'' 被当真步骤名查，报「没有步骤 ''」）。
        if not sid:
            return None
        if sid in self.steps:
            return self.steps.index(sid)
        host = self._gate_host(sid)
        if host:
            raise ValueError(
                f"{sid!r} 是挂在 {host!r} 出口的闸，不是独立的 pipeline 步骤，"
                f"不能单独 `step {sid}`——用 `step {host}` 代替"
                f"（跑完 {host} 会自动跟着跑 {sid}）。"
            )
        raise ValueError(f"pipeline {self.id} 没有步骤 {sid!r}")

    def slice(self, from_step: str | None = None, to_step: str | None = None) -> list[str]:
        i = self._index(from_step)
        i = i if i is not None else 0
        j = self._index(to_step)
        j = j + 1 if j is not None else len(self.steps)
        if i >= j:
            raise ValueError(f"步骤范围为空: {from_step} → {to_step}")
        return self.steps[i:j]

    def edges(self) -> list[tuple[str, str, str]]:
        """(上游, 下游, 产物种类) 三元组，给控制台画图。"""
        out = []
        for sid in self.steps:
            me = STEPS[sid]
            wants = (*me.spec.consumes, *me.spec.optional_consumes)
            for up in self.upstream(sid):
                kinds = [k for k in wants if k in _produces(STEPS[up])] or ["needs"]
                for k in kinds:
                    out.append((up, sid, k))
        return out

    def validate(self) -> None:
        seen: set[str] = set()
        for sid in self.steps:
            if sid not in STEPS:
                raise ValueError(f"pipeline {self.id}: 未注册的 Step {sid!r}")
            s = STEPS[sid]
            provided = {k for p in seen for k in _produces(STEPS[p])}
            wants = (*s.spec.consumes, *s.spec.optional_consumes)
            missing = [k for k in wants if k not in provided and k not in _EXTERNAL_KINDS]
            # 可选上游的生产者**在这条管线里**就必须排在前面（写反了顺序要报）；整条管线都没有它的生产者，
            # 就当这条链里这一路永远缺席（`provides()` 为假，读不到、不进指纹）。
            # 2026-11-03 改：以前一律要求有生产者，cell_shrink 10-22 加可选上游 seals 后 modern_body
            # 整条加载不了，默认选管线时被 `except` 吞掉、现代书悄悄退回刻本链。
            hard = [k for k in missing if k in s.spec.consumes or self.provides(k)]
            if hard:
                raise ValueError(f"pipeline {self.id}: {sid} 需要 {hard}，但前面没有步骤产出它")
            seen.add(sid)

    def provides(self, kind_id: str) -> bool:
        """这条管线里有没有步骤（含出口挂的闸）产出 `kind_id`；`raw_page` 等外部种类算有。"""
        return kind_id in _EXTERNAL_KINDS or any(kind_id in _produces(STEPS[s]) for s in self.steps)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "selector": self.selector,
            "steps": [STEPS[s].describe() for s in self.steps],
            "edges": [{"from": a, "to": b, "kind": k} for a, b, k in self.edges()],
            "notes": self.notes,
        }


# 由 Book 提供、不由任何 Step 产出的种类
_EXTERNAL_KINDS = {"raw_page"}


SKELETON_ID = "_skeleton"


def expand_slots(chain: dict, skeleton: dict, pid: str = "?") -> list[str]:
    """骨架 + 链 yaml 的 `slots:` → 完整的步骤顺序（2026-11-03 管线重组方案 B 第二期）。

    骨架 `steps:` 里写步骤 id 原样保留，写 `{slot: 名}` 的换成链里这个槽位的步骤表（链没写就用骨架 `slots:` 的缺省，
    都没有且在 `required` 里就报错）。链 yaml 里点了骨架没有的槽位也报错——拼错槽位名不能悄悄不生效。"""
    given = chain.get("slots") or {}
    defaults = skeleton.get("slots") or {}
    names = [x["slot"] for x in skeleton.get("steps", []) if isinstance(x, dict)]
    unknown = [k for k in given if k not in names]
    if unknown:
        raise ValueError(f"pipeline {pid}: slots: 里有骨架没有的槽位 {unknown}，骨架槽位是 {names}")
    missing = [k for k in (skeleton.get("required") or []) if k not in given]
    if missing:
        raise ValueError(f"pipeline {pid}: slots: 缺必填槽位 {missing}")
    out: list[str] = []
    for x in skeleton.get("steps", []):
        if isinstance(x, dict):
            lst = given[x["slot"]] if x["slot"] in given else defaults.get(x["slot"], [])
            if not isinstance(lst, list):
                raise ValueError(f"pipeline {pid}: 槽位 {x['slot']} 要写成步骤 id 的列表")
            out.extend(str(i) for i in lst)
        else:
            out.append(str(x))
    return out


def load_pipeline(pid: str, pipelines_dir: Path | None = None) -> Pipeline:
    import open_guji_cv.steps  # noqa: F401  —— 触发 Step 注册

    pdir = pipelines_dir or PIPELINES_DIR
    path = pdir / f"{pid}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"没有这条 pipeline: {path}")
    from .yaml_cache import load_yaml_cached
    d = load_yaml_cached(path)
    if "slots" in d:                  # 链 yaml 只写槽位，步骤顺序由骨架展开
        if "steps" in d:
            raise ValueError(f"pipeline {pid}: slots: 和 steps: 不能同时写")
        sk_path = pdir / f"{SKELETON_ID}.yaml"
        if not sk_path.exists():
            raise FileNotFoundError(f"pipeline {pid} 用了 slots:，但没有骨架 {sk_path}")
        d["steps"] = expand_slots(d, load_yaml_cached(sk_path), pid)
    params_raw = d.get("params") or {}
    if not isinstance(params_raw, dict) or any(not isinstance(v, dict) for v in params_raw.values()):
        raise ValueError(f"pipeline {pid} 的 params: 必须是 {{step_id: {{字段: 值}}}}")
    p = Pipeline(
        id=d.get("id", pid), title=d.get("title", pid),
        steps=[str(s) for s in d.get("steps", [])],
        selector=d.get("selector") or {}, needs=d.get("needs") or {},
        notes=d.get("notes", ""),
        params={str(k): dict(v) for k, v in params_raw.items()},
    )
    p.validate()
    for sid in p.params:
        if sid not in STEPS:
            raise ValueError(f"pipeline {pid} 的 params: 里有未注册的 Step {sid!r}")
    return p


def list_pipelines(pipelines_dir: Path | None = None) -> list[str]:
    d = pipelines_dir or PIPELINES_DIR
    return sorted(p.stem for p in d.glob("*.yaml") if not p.stem.startswith("_")) if d.exists() else []


DEFAULT_PIPELINE_ID = "keben_body_v2"


def default_pipeline_id(book, pipelines_dir: Path | None = None) -> str:
    """这册书默认走哪条管线（2026-11-03 管线重组方案 B 第一期起以套书为准）：

    1. 册 yaml 显式写了 `pipeline:` 的照它（旧写法，兼容留着）；
    2. 写了 `seg_set:` 的按套书推（`core/seg_set.SEG_SET_PIPELINE`）；
    3. 都没写，按 `edition` 找 `selector.edition` 相同的那条（唯一时）；找不到或多于一条都退回
       `keben_body_v2`——刻本链是历史默认，不能因为多了一条现代链就变。"""
    explicit = getattr(book, "pipeline", None)
    if explicit:
        return explicit
    from .seg_set import SEG_SET_PIPELINE, _book_code
    ss = getattr(book, "seg_set", None)
    if ss and ss in SEG_SET_PIPELINE:
        return SEG_SET_PIPELINE[ss]
    bc = _book_code()
    if bc is not None and ss in (None, bc.name):
        return bc.pipeline              # 书仓 code/code.yaml 的 base（2026-11-09 书级代码）
    edition = getattr(book, "edition", None)
    hits = []
    for pid in list_pipelines(pipelines_dir):
        try:
            pl = load_pipeline(pid, pipelines_dir)
        except Exception:      # noqa: BLE001 —— 一条坏 yaml 不该让选默认管线炸
            continue
        if pl.selector.get("edition") == edition:
            hits.append(pid)
    if edition == "keben" or len(hits) != 1:
        return DEFAULT_PIPELINE_ID
    return hits[0]


def base_param_layers(pipeline: Pipeline, book) -> list[tuple[str, dict[str, dict]]]:
    """册配置之下的参数层，低 → 高：管线 yaml `params:`、套书缺省 `books/<套书>/defaults.yaml`。

    2026-11-03 管线重组方案 B 第一期：同一份 Step 代码在不同套书下的缺省参数写在套书目录里，
    不再写在管线 yaml（现有三条管线的 `params:` 已搬空，这一层只为兼容留着）。"""
    from .seg_set import seg_set_for_run, seg_set_params
    ss = seg_set_for_run(book, pipeline.id)
    sp = seg_set_params(ss)
    for sid in sp:
        if sid not in STEPS:
            raise ValueError(f"套书 {ss} 的 defaults.yaml params: 里有未注册的 Step {sid!r}")
    return [("管线 yaml", dict(pipeline.params or {})), (f"套书缺省（{ss}）", sp)]


def base_params(pipeline: Pipeline, book) -> dict[str, dict]:
    """`base_param_layers` 按字段合并（上层优先；写 `null` = 去掉下层的值）。"""
    merged: dict[str, dict] = {}
    for _, layer in base_param_layers(pipeline, book):
        for sid, kv in layer.items():
            tgt = merged.setdefault(sid, {})
            for k, v in kv.items():
                if v is None:
                    tgt.pop(k, None)
                else:
                    tgt[k] = v
    return merged
