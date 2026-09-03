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
        """直接上游：产出本步 consumes 的那些步 + needs 里显式写的。"""
        me = STEPS[sid]
        ups: list[str] = []
        for other in self.steps:
            if other == sid:
                break
            o = STEPS[other]
            if any(k in o.spec.produces for k in me.spec.consumes) or other in self.needs.get(sid, []):
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

    def slice(self, from_step: str | None = None, to_step: str | None = None) -> list[str]:
        i = self.steps.index(from_step) if from_step else 0
        j = self.steps.index(to_step) + 1 if to_step else len(self.steps)
        if i >= j:
            raise ValueError(f"步骤范围为空: {from_step} → {to_step}")
        return self.steps[i:j]

    def edges(self) -> list[tuple[str, str, str]]:
        """(上游, 下游, 产物种类) 三元组，给控制台画图。"""
        out = []
        for sid in self.steps:
            me = STEPS[sid]
            for up in self.upstream(sid):
                kinds = [k for k in me.spec.consumes if k in STEPS[up].spec.produces] or ["needs"]
                for k in kinds:
                    out.append((up, sid, k))
        return out

    def validate(self) -> None:
        seen: set[str] = set()
        for sid in self.steps:
            if sid not in STEPS:
                raise ValueError(f"pipeline {self.id}: 未注册的 Step {sid!r}")
            s = STEPS[sid]
            provided = {k for p in seen for k in STEPS[p].spec.produces}
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
