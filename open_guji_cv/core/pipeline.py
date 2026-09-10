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

    # ── 图 ───────────────────────────────────────────────────────────
    def step(self, sid: str) -> Step:
        return STEPS[sid]

    def upstream(self, sid: str) -> list[str]:
        """直接上游：产出本步 consumes 的那些步（含它们出口挂的闸产出的）+ needs 里显式写的。"""
        me = STEPS[sid]
        ups: list[str] = []
        for other in self.steps:
            if other == sid:
                break
            o = STEPS[other]
            if any(k in _produces(o) for k in me.spec.consumes) or other in self.needs.get(sid, []):
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
            for up in self.upstream(sid):
                kinds = [k for k in me.spec.consumes if k in _produces(STEPS[up])] or ["needs"]
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
            missing = [k for k in s.spec.consumes if k not in provided and k not in _EXTERNAL_KINDS]
            if missing:
                raise ValueError(f"pipeline {self.id}: {sid} 需要 {missing}，但前面没有步骤产出它")
            seen.add(sid)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "selector": self.selector,
            "steps": [STEPS[s].describe() for s in self.steps],
            "edges": [{"from": a, "to": b, "kind": k} for a, b, k in self.edges()],
            "notes": self.notes,
        }


# 由 Book 提供、不由任何 Step 产出的种类
_EXTERNAL_KINDS = {"raw_page"}


def load_pipeline(pid: str, pipelines_dir: Path | None = None) -> Pipeline:
    import open_guji_cv.steps  # noqa: F401  —— 触发 Step 注册

    path = (pipelines_dir or PIPELINES_DIR) / f"{pid}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"没有这条 pipeline: {path}")
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    p = Pipeline(
        id=d.get("id", pid), title=d.get("title", pid),
        steps=[str(s) for s in d.get("steps", [])],
        selector=d.get("selector") or {}, needs=d.get("needs") or {},
        notes=d.get("notes", ""),
    )
    p.validate()
    return p


def list_pipelines(pipelines_dir: Path | None = None) -> list[str]:
    d = pipelines_dir or PIPELINES_DIR
    return sorted(p.stem for p in d.glob("*.yaml")) if d.exists() else []
