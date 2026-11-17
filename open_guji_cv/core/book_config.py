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
#: 书 id、册序（`core/volume_id.py`）：书 id 写在基础配置、册序写在册 yaml，但都是身份，运行覆盖不许改
VOLUME_ID_KEYS = frozenset({"book_id", "volume", "volume_width", "chapter_width"})
#: 实测的版式先验：换书必须重标，不许写进基础配置（运行覆盖可以，做实验用）
MEASURED_KEYS = frozenset({"bottom_gap", "period_prior", "frame_height", "col_pitch", "outer_shift",
                           "outer_gap", "preclean", "page_split", "dev_set", "layout_hints", "page_kinds"})
FORBIDDEN_IN_DEFAULTS = IDENTITY_KEYS | MEASURED_KEYS
FORBIDDEN_IN_OVERRIDE = IDENTITY_KEYS | VOLUME_ID_KEYS


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
        raise BookConfigError(f"--override 不许改 {', '.join(bad)}（身份、图源、书 id 与册序只能改册配置）")
    return d


def merge_override_env(raw: str) -> str:
    """把 `--override` 的 JSON 叠在本进程已有的 `GUJI_BOOK_OVERRIDE` 上（同键后者胜，`params` 按步骤再叠一层），
    返回合并后的 JSON。已有的覆盖多半是准备脚本记的改值（rerun_prep.sh：corpus／glyph_pin／cv_version）。"""
    try:
        new = json.loads(raw)
    except ValueError as e:
        raise BookConfigError(f"--override 不是合法 JSON：{e}") from None
    if not isinstance(new, dict):
        raise BookConfigError("--override 要是 JSON 对象，如 {\"corpus\": 23}")
    old = run_override()
    out = {**old, **new}
    if isinstance(old.get("params"), dict) and isinstance(new.get("params"), dict):
        ps = {sid: dict(kv) for sid, kv in old["params"].items()}
        for sid, kv in new["params"].items():
            ps[sid] = {**ps.get(sid, {}), **kv} if isinstance(kv, dict) and isinstance(ps.get(sid), dict) else kv
        out["params"] = ps
    return json.dumps(out, ensure_ascii=False)


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
    from .page_kinds import fold_layer, reject_old_syntax
    from .ref_profile import fold_layer as fold_ref_profile
    raw_ls = layers(book_yaml, apply_override=apply_override)
    for n, ly in raw_ls:
        if n != "运行覆盖":
            reject_old_syntax(Path(book_yaml).stem, n, ly)
    from .lib_pins import expand_layer
    try:      # 参校本属性：各层先把标量归一成 {default: x} 再合并（否则标量盖映射丢另一半）；基础配置不许写 segments
        # 四库版本简写 `pin: c31-g19-m2-k3` 逐层展开成分开的键（core/lib_pins.py），上层照常压下层
        ls = [(n, fold_ref_profile(n, fold_layer(n, expand_layer(ly, f"{n}：")), allow_segments=(n != "基础配置")))
              for n, ly in raw_ls]
    except ValueError as e:
        raise BookConfigError(str(e)) from None
    if len(ls) == 1:
        d = copy.deepcopy(ls[0][1])
    else:
        d = {}
        for _, layer in ls:
            d = merge(d, layer)
    return expand_book_placeholders(d, str(d.get("id") or Path(book_yaml).stem))


#: 册配置里可以写 `{book}` 占位的参数（2026-11-06，三套书配置归并）：基础配置写一行，按册展开。
#: 展开在合层之后、建 Step 参数之前做，进参数 dump 的是展开后的路径，与逐册写死逐字节相同，指纹不变。
BOOK_PLACEHOLDER_FIELDS: tuple[tuple[str, str], ...] = (
    ("row_segment", "layout_prior"),
)


def expand_book_placeholders(d: dict, book_id: str) -> dict:
    """把 `BOOK_PLACEHOLDER_FIELDS` 里字符串值的 `{book}` 换成册 id（如殿本基础配置
    `layout_prior: corpus/daizhige/layout_slots_qiefen_{book}.jsonl` → vol50 的 `…_vol50.jsonl`）。
    改到的那几层字典先浅拷贝（合层结果可能与 yaml 缓存共用子字典），返回 `d`。"""
    ps = d.get("params")
    if not isinstance(ps, dict):
        return d
    for sid, field in BOOK_PLACEHOLDER_FIELDS:
        kv = ps.get(sid)
        if isinstance(kv, dict) and isinstance(kv.get(field), str) and "{book}" in kv[field]:
            ps = d["params"] = dict(ps)
            ps[sid] = {**kv, field: kv[field].replace("{book}", book_id)}
    return d


def run_override_params() -> dict[str, dict]:
    """运行覆盖里的 `params:`——在引擎里当「调用方显式参数」用（压过册 yaml，可以把开关关掉）。"""
    p = run_override().get("params") or {}
    if not isinstance(p, dict) or any(not isinstance(v, dict) for v in p.values()):
        raise BookConfigError("--override 的 params 要是 {step_id: {字段: 值}}")
    return p


def params_provenance(book_yaml: Path, pipeline_params: dict | None = None,
                      base_layers: list[tuple[str, dict]] | None = None) -> dict[str, tuple[object, str]]:
    """`params:` 逐字段的生效值与来源层：`{"<step>.<字段>": (值, 层名)}`，给 `guji book show --effective` 用。

    层从低到高：管线 yaml < 套书缺省（`base_layers`，`core/pipeline.base_param_layers` 给；不给就只算
    `pipeline_params` 一层）< 基础配置 < 册 yaml < 运行覆盖，与 `Engine.__init__` 的合并一致；
    某层写 `null` = 去掉下层的值（回 Step 默认，不列出）。不含 Step 默认值（没列出的字段就是默认）。"""
    out: dict[str, tuple[object, str]] = {}
    base = base_layers if base_layers is not None else [("管线 yaml", pipeline_params or {})]
    ls = [(name, {"params": pp or {}}) for name, pp in base] + layers(book_yaml)
    from .page_kinds import load_page_kinds, to_params
    for name, layer in ls:
        # 页型表 `page_kinds` 翻成的三个参数记在同一层，来源标「（page_kinds）」；同层写了老写法的在它之上
        pk = to_params(load_page_kinds(layer.get("page_kinds")))
        explicit = layer.get("params") or {}
        for sid, kv in pk.items():
            for k, v in kv.items():
                key = f"{sid}.{k}"
                if (explicit.get(sid) or {}).get(k) in (None, [], ()):
                    out[key] = (v, f"{name}（page_kinds）")
        for sid, kv in explicit.items():
            if not isinstance(kv, dict):
                continue
            for k, v in kv.items():
                key = f"{sid}.{k}"
                if v is None:
                    out.pop(key, None)
                else:
                    out[key] = (v, name)
    return dict(sorted(out.items()))


def provenance(book_yaml: Path) -> dict[str, str]:
    """顶层字段 → 来自哪一层（取最高层），给 `guji book show --effective` 用。"""
    src: dict[str, str] = {}
    for name, layer in layers(book_yaml):
        for k in layer:
            src[k] = name
    return src
