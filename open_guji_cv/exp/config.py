# -*- coding: utf-8 -*-
"""实验配置：一份 yaml = 一个实验，只写与基线不同的参数。

```yaml
name: shadow_veto-vol05
books: [vol05]
snapshot: /path/to/products        # 含 <book>/<step>/ 的产物根（只读，快照或 `guji snapshot` 出来的目录）
from: seed_admit                   # 第一个受影响的步；之前的步从快照复用
to: seed_admit
pages: all                         # 跑哪些页：all（快照里有上游的页）/ body / 页号表达式
base:                              # 变体 A；省略 = 当前代码的默认参数
  params: {}
variants:
  B:
    params:
      seed_admit: {shadow_veto: true, shadow_conf: 0.8}
book_params: keep                  # keep：基线 = 书 yaml 现行 params:；ignore：基线 = 代码默认值
match: exact                       # exact：码位相同才算对（口径 A，忠于刻本原形，用户 10-07 定）；semantic：异体等价也算对
eval:                              # 评测口径，所有变体一样，与产品默认值无关
  use_human_verdicts: false        # 缺省就是 false：不让 Step7 抄人裁再拿人裁考它
labels:
  - {source: human_events}
  - {source: vision, path: reports/vol05/看图结论.jsonl, selection: picked}
guardrails:
  - {metric: admit_err_rate, scope: body, op: "<=", ref: base}
  - {metric: review_rate, scope: body, op: "<=", ref: base, delta: 0.005}
```

参数名**逐个对 Step 的 Params 校验**：pydantic 缺省忽略多余字段，`juan_rule` 写到没有这个字段的
代码上会被静默吞掉、两边跑成一样——这里直接报错。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..errors import BadRequest

#: 实验产物的缺省根（相对工作区）。
EXP_REL = "experiments"
BASE_NAME = "A"


@dataclass
class Variant:
    name: str
    params: dict[str, dict] = field(default_factory=dict)
    note: str = ""


@dataclass
class ExpConfig:
    name: str
    books: list[str]
    variants: list[Variant]                    # 第一个是基线
    from_step: str = "seed_admit"
    to_step: str = "seed_admit"
    pipeline: str = "keben_body_v2"
    pages: str | list[int] = "all"
    book_params: str = "keep"                  # keep / ignore：书 yaml 的 params: 算不算进基线
    match: str = "exact"                       # exact / semantic：放行字与标签字怎样算「对」
    snapshot: str | None = None
    root: str | None = None
    eval_params: dict[str, dict] = field(default_factory=dict)
    labels: list[dict] = field(default_factory=list)
    guardrails: list[dict] = field(default_factory=list)
    bootstrap: int = 2000
    seed: int = 0
    source: str | None = None                  # yaml 路径（记账用）

    @property
    def base(self) -> Variant:
        return self.variants[0]

    def variant(self, name: str) -> Variant:
        for v in self.variants:
            if v.name == name:
                return v
        raise BadRequest(f"实验 {self.name} 没有变体 {name}")

    def run_params(self, v: Variant) -> dict[str, dict]:
        """变体实际跑的覆盖层：评测口径 ∪ 变体参数（变体优先）。"""
        return merge_params(self.eval_params, v.params)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "books": list(self.books), "from": self.from_step, "to": self.to_step,
            "pipeline": self.pipeline, "pages": self.pages, "book_params": self.book_params,
            "match": self.match, "snapshot": self.snapshot, "root": self.root,
            "base": {"name": self.base.name, "params": self.base.params, "note": self.base.note},
            "variants": {v.name: {"params": v.params, "note": v.note} for v in self.variants[1:]},
            "eval": {"params": self.eval_params},
            "labels": self.labels, "guardrails": self.guardrails,
            "bootstrap": self.bootstrap, "seed": self.seed,
        }


def merge_params(*layers: dict[str, dict] | None) -> dict[str, dict]:
    """按 Step 合并多层 `{step: {字段: 值}}`，后者优先（与 `Engine` 的合并口径一致）。"""
    out: dict[str, dict] = {}
    for layer in layers:
        for sid, kv in (layer or {}).items():
            out.setdefault(sid, {}).update(copy.deepcopy(kv or {}))
    return out


def _params_block(d: Any, where: str) -> dict[str, dict]:
    if d is None:
        return {}
    if not isinstance(d, dict) or not all(isinstance(v, dict) for v in d.values()):
        raise BadRequest(f"{where}: params 要写成 {{step_id: {{字段: 值}}}}")
    return {str(k): dict(v) for k, v in d.items()}


def _variant(name: str, d: Any, where: str) -> Variant:
    d = d or {}
    if not isinstance(d, dict):
        raise BadRequest(f"{where}: 变体要写成 mapping")
    extra = set(d) - {"params", "note", "name"}
    if extra:
        raise BadRequest(f"{where}: 不认识的键 {sorted(extra)}（变体只写 params / note；"
                         f"跑不同代码的变体暂不支持，见 overview#457）")
    return Variant(name=str(d.get("name") or name), params=_params_block(d.get("params"), where),
                   note=str(d.get("note") or ""))


def _eval_block(d: Any) -> dict[str, dict]:
    """`eval:` → 评测口径覆盖层。`use_human_verdicts` 是 seed_admit 的捷径，缺省 false。"""
    d = dict(d or {})
    params = _params_block(d.pop("params", None), "eval")
    uhv = d.pop("use_human_verdicts", False)
    if d:
        raise BadRequest(f"eval: 不认识的键 {sorted(d)}")
    params.setdefault("seed_admit", {}).setdefault("use_human_verdicts", bool(uhv))
    return params


def from_dict(d: dict, source: str | None = None) -> ExpConfig:
    if not isinstance(d, dict):
        raise BadRequest("实验 yaml 顶层要是 mapping")
    known = {"name", "books", "from", "to", "pipeline", "pages", "book_params", "match", "snapshot", "root", "base",
             "variants", "eval", "labels", "guardrails", "bootstrap", "seed"}
    extra = set(d) - known
    if extra:
        raise BadRequest(f"实验 yaml 有不认识的键：{sorted(extra)}")
    name = d.get("name") or (Path(source).stem if source else None)
    if not name:
        raise BadRequest("实验要有 name")
    books = d.get("books") or []
    if isinstance(books, str):
        books = [b.strip() for b in books.split(",") if b.strip()]
    if not books:
        raise BadRequest("实验要有 books")
    base_d = d.get("base") or {}
    variants = [_variant(BASE_NAME, base_d, "base")]
    vs = d.get("variants") or {}
    if not isinstance(vs, dict) or not vs:
        raise BadRequest("实验至少要一个 variants（与基线比较的一方）")
    for vn, vd in vs.items():
        variants.append(_variant(str(vn), vd, f"variants.{vn}"))
    names = [v.name for v in variants]
    if len(set(names)) != len(names):
        raise BadRequest(f"变体重名：{names}")
    for v in names:
        if not v or "/" in v or v.startswith("_") or v in (".", ".."):
            raise BadRequest(f"变体名不合法：{v!r}")
    cfg = ExpConfig(
        name=str(name), books=[str(b) for b in books], variants=variants,
        from_step=str(d.get("from") or "seed_admit"), to_step=str(d.get("to") or "seed_admit"),
        pipeline=str(d.get("pipeline") or "keben_body_v2"), pages=d.get("pages") or "all",
        book_params=str(d.get("book_params") or "keep"), match=str(d.get("match") or "exact"),
        snapshot=d.get("snapshot"), root=d.get("root"), eval_params=_eval_block(d.get("eval")),
        labels=list(d.get("labels") or []), guardrails=list(d.get("guardrails") or []),
        bootstrap=int(d.get("bootstrap", 2000)), seed=int(d.get("seed", 0)), source=source)
    if cfg.match not in ("exact", "semantic"):
        raise BadRequest(f"match 只能是 exact / semantic：{cfg.match!r}")
    if cfg.book_params not in ("keep", "ignore"):
        raise BadRequest(f"book_params 只能是 keep / ignore：{cfg.book_params!r}")
    if not cfg.name or "/" in cfg.name or cfg.name.startswith("_"):
        raise BadRequest(f"实验名不合法：{cfg.name!r}")
    return cfg


def load(path: str | Path) -> ExpConfig:
    p = Path(path)
    with open(p, encoding="utf-8") as f:
        return from_dict(yaml.safe_load(f) or {}, source=str(p))


def from_pair(base: str | Path | None, var: list[str | Path], *, books: list[str],
              from_step: str = "seed_admit", to_step: str = "seed_admit", name: str | None = None,
              **kw) -> ExpConfig:
    """issue 原定的短写法 `--base A.yaml --var B.yaml [--var C.yaml]`：每份 yaml 是一个变体
    （`{params: …}`，或直接 `{step: {字段: 值}}`），变体名取文件名。"""
    def read(p) -> tuple[str, dict]:
        with open(p, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        if "params" not in d and "note" not in d:
            d = {"params": d}
        return Path(p).stem, d
    variants: dict[str, dict] = {}
    base_d: dict = {}
    if base:
        _, base_d = read(base)
    for p in var:
        vn, vd = read(p)
        variants[vn] = vd
    d = {"name": name or "_".join(variants) or "exp", "books": books, "from": from_step, "to": to_step,
         "base": base_d, "variants": variants, **{k: v for k, v in kw.items() if v is not None}}
    return from_dict(d)


def effective_params(cfg: ExpConfig, v: Variant, book_params: dict | None) -> dict[str, dict]:
    """一个变体在一册书上**实际**跑的参数：(书 yaml 的 params:，若 keep) ∪ 评测口径 ∪ 变体覆盖。

    为什么框架自己合并、再把书级参数清空交给引擎：引擎的书级覆盖（`core/step.py::_with_book_params`）
    只替换「仍是默认值」的字段——变体显式写成默认值（如 `shadow_veto: false`）时分不清，会被书 yaml
    改回去，A/B 两边就跑成一样。这里先合好，引擎那层就不再起作用。"""
    base = (book_params or {}) if cfg.book_params == "keep" else {}
    return merge_params(base, cfg.run_params(v))


def validate_params(cfg: ExpConfig) -> None:
    """每个变体的覆盖层逐字段对 Step 的 Params 校验（不认识的字段报错，值类型交给 pydantic）。"""
    import open_guji_cv.steps  # noqa: F401  —— 触发 Step 注册
    from ..core.step import STEPS

    for v in cfg.variants:
        for sid, kv in cfg.run_params(v).items():
            if sid not in STEPS:
                raise BadRequest(f"变体 {v.name}: 没有这一步 {sid!r}")
            model = STEPS[sid].spec.params
            if model is None:
                raise BadRequest(f"变体 {v.name}: {sid} 没有参数")
            unknown = sorted(set(kv) - set(model.model_fields))
            if unknown:
                raise BadRequest(f"变体 {v.name}: {sid} 没有参数 {unknown}"
                                 f"（当前代码里不存在——这个开关是不是还在别的分支上？）")
            try:
                model(**kv)
            except Exception as e:  # pydantic.ValidationError
                raise BadRequest(f"变体 {v.name}: {sid} 参数不合法：{e}") from e
