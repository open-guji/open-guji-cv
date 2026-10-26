"""册配置分层与运行覆盖（设计：doc/design/册配置分层与运行覆盖.md）。

生效顺序（后者覆盖前者）：工作区基础配置 `config/book_defaults.yaml` < 册 yaml `books/<册>.yaml`
< 本次运行覆盖（环境变量 `GUJI_BOOK_OVERRIDE`，由 `guji … --override` 设；子进程自动继承）。
Step 默认值、管线 yaml `params:` 在更下面，由 `core/engine.py` 处理。

合并规则：映射按键深合并；标量、列表整体替换；上层写 `null` 就是 null（`expected_cols: null` 等有意义）；
唯独 `params:` 里的字段写 `null` = 去掉下层的值、回到 Step 默认。

没有基础配置、没有运行覆盖时，`effective_book_dict` 返回的就是册 yaml 解析结果本身，行为与分层前逐位相同。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

OVERRIDE_ENV = "GUJI_BOOK_OVERRIDE"

#: 身份与图源：只能写在册 yaml 里，基础配置、运行覆盖都不许写
IDENTITY_KEYS = frozenset({"id", "title", "raw_dir", "raw_pattern", "pages", "sets", "freeze"})
#: 实测的版式先验：换书必须重标，不许写进基础配置（运行覆盖可以，做实验用）
MEASURED_KEYS = frozenset({"bottom_gap", "period_prior", "frame_height", "col_pitch", "outer_shift",
                           "outer_gap", "preclean", "page_split", "dev_set"})
FORBIDDEN_IN_DEFAULTS = IDENTITY_KEYS | MEASURED_KEYS
FORBIDDEN_IN_OVERRIDE = IDENTITY_KEYS


class BookConfigError(ValueError):
    """基础配置或运行覆盖写错了。消息直接给人看。"""


def merge(base: dict, over: dict, *, _in_params: bool = False) -> dict:
    """`over` 叠在 `base` 上，返回新字典，不改入参。"""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if v is None and _in_params:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v, _in_params=_in_params or k == "params")
        else:
            out[k] = copy.deepcopy(v)
    return out


def defaults_path(book_yaml: Path) -> Path:
    """与 `books/` 同级的 `config/book_defaults.yaml`（同 `config/codepoints.yaml` 的先例）。"""
    return Path(book_yaml).parent.parent / "config" / "book_defaults.yaml"


def load_defaults(book_yaml: Path) -> dict:
    p = defaults_path(book_yaml)
    if not p.exists():
        return {}
    from .yaml_cache import load_yaml_cached
    d = load_yaml_cached(p) or {}
    if not isinstance(d, dict):
        raise BookConfigError(f"{p} 顶层应是映射")
    bad = sorted(set(d) & FORBIDDEN_IN_DEFAULTS)
    if bad:
        raise BookConfigError(
            f"{p} 里不许写 {', '.join(bad)}：身份、图源、实测先验只能写在册 yaml（换书要重标，不能共用）")
    return d


def run_override() -> dict:
    """本进程的运行覆盖（`GUJI_BOOK_OVERRIDE`，JSON 对象）；没设返回空字典。"""
    raw = os.environ.get(OVERRIDE_ENV)
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except ValueError as e:
        raise BookConfigError(f"{OVERRIDE_ENV}（--override）不是合法 JSON：{e}") from None
    if not isinstance(d, dict):
        raise BookConfigError("--override 要是 JSON 对象，如 {\"corpus\": 23}")
    bad = sorted(set(d) & FORBIDDEN_IN_OVERRIDE)
    if bad:
        raise BookConfigError(f"--override 不许改 {', '.join(bad)}（身份与图源只能改册 yaml）")
    return d


def layers(book_yaml: Path, *, apply_override: bool = True) -> list[tuple[str, dict]]:
    """各层的原样内容，低 → 高：[(层名, 字典)…]；没有的层不列。"""
    from .yaml_cache import load_yaml_cached
    out: list[tuple[str, dict]] = []
    dflt = load_defaults(book_yaml)
    if dflt:
        out.append(("基础配置", dflt))
    out.append(("册 yaml", load_yaml_cached(book_yaml) or {}))
    if apply_override:
        ov = run_override()
        if ov:
            out.append(("运行覆盖", ov))
    return out


def effective_book_dict(book_yaml: Path, *, apply_override: bool = True) -> dict:
    """册 yaml 合上基础配置与运行覆盖后的生效字典（`load_book` 的入口）。"""
    ls = layers(book_yaml, apply_override=apply_override)
    if len(ls) == 1:
        return copy.deepcopy(ls[0][1])
    d: dict = {}
    for _, layer in ls:
        d = merge(d, layer)
    return d


def run_override_params() -> dict[str, dict]:
    """运行覆盖里的 `params:`——在引擎里当「调用方显式参数」用（压过册 yaml，可以把开关关掉）。"""
    p = run_override().get("params") or {}
    if not isinstance(p, dict) or any(not isinstance(v, dict) for v in p.values()):
        raise BookConfigError("--override 的 params 要是 {step_id: {字段: 值}}")
    return p


def provenance(book_yaml: Path) -> dict[str, str]:
    """顶层字段 → 来自哪一层（取最高层），给 `guji book show --effective` 用。"""
    src: dict[str, str] = {}
    for name, layer in layers(book_yaml):
        for k in layer:
            src[k] = name
    return src
