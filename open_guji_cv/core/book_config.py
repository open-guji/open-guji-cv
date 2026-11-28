"""册配置分层与运行覆盖（设计：doc/design/册配置分层与运行覆盖.md）。

生效顺序（后者覆盖前者）：组配置（基础配置 `groups: {config: <组>@<版>}` 指定，见下）< 工作区基础配置
`config/book_defaults.yaml` < 册 yaml `books/<册>.yaml` < 本次运行覆盖（环境变量 `GUJI_BOOK_OVERRIDE`，由 `guji … --override` 设；子进程自动继承）。
Step 默认值、管线 yaml `params:` 在更下面，由 `core/engine.py` 处理。

合并规则：映射按键深合并；标量、列表整体替换；上层写 `null` 就是 null（`expected_cols: null` 等有意义）；
唯独 `params:` 里的字段写 `null` = 去掉下层的值、回到 Step 默认。

没有基础配置、没有运行覆盖时，`effective_book_dict` 返回的就是册 yaml 解析结果本身，行为与分层前逐位相同。

## 组层（2026-11-28，CV0；设计 Claude Doc「配置六层与组层设计」）

一套丛书或一种版刻字体共用的配置（如 wyg 文渊阁写本、wyd 武英殿刻本）。书在基础配置里声明：

    groups:
      config: wyg@1      # 配置组，恰好一个；@ 后是版本号（只增不改）
      glyph: [wyg]       # 字形／语料／模型各系统的组：这里只登记、不参与合并（实际借库、码表、模型仍按各自的钉子）

组配置是中心库只读工作区 `group-<组>` 里的 `config/group/v<版>.yaml`（形状同基础配置；顶层 `meta:` 是说明，不进合并），
`guji db pull` 拉成 `borrowed_root('group-<组>')` 下的只读副本。钉了而副本没有 → 报错，不当成没组。
`groups:` 只许写在基础配置；组里禁写 `FORBIDDEN_IN_GROUP` 与 `FORBIDDEN_GROUP_PARAMS`。组名、版本号不进指纹，生效值进。
旧 cv（不认组层）读到 `groups:` 静默忽略，所以入组时书里与组同值的键要等升到认组层的 cv 再删。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

OVERRIDE_ENV = "GUJI_BOOK_OVERRIDE"

#: 身份与图源（含缺页 `gaps`：这一册图源的事实）：只能写在册 yaml 里，基础配置、运行覆盖都不许写
IDENTITY_KEYS = frozenset({"id", "title", "raw_dir", "raw_pattern", "pages", "sets", "freeze", "gaps"})
#: 书 id、册序（`core/volume_id.py`）：书 id 写在基础配置、册序写在册 yaml，但都是身份，运行覆盖不许改
VOLUME_ID_KEYS = frozenset({"book_id", "volume", "volume_width", "chapter_width"})
#: 实测的版式先验：换书必须重标，不许写进基础配置（运行覆盖可以，做实验用）
MEASURED_KEYS = frozenset({"bottom_gap", "period_prior", "frame_height", "col_pitch", "outer_shift",
                           "outer_gap", "preclean", "page_split", "dev_set", "layout_hints", "page_kinds"})
FORBIDDEN_IN_DEFAULTS = IDENTITY_KEYS | MEASURED_KEYS
FORBIDDEN_IN_OVERRIDE = IDENTITY_KEYS | VOLUME_ID_KEYS | {"groups"}

GROUPS_KEY = "groups"
#: `groups:` 里认的系统：config 参与合并；其余只登记（各系统仍按自己的钉子取版本）
GROUP_SYSTEMS = ("config", "glyph", "corpus", "model")
#: 组配置里不许写的顶层键：身份、图源、实测先验、书的身份与钉子、绑在这部书文字上的数据，以及 manager 直接读的书级键
FORBIDDEN_IN_GROUP = FORBIDDEN_IN_DEFAULTS | VOLUME_ID_KEYS | frozenset({
    "book_title", "book_edition", "seg_set", "pipeline",
    "corpus", "glyph_pin", "model", "code", "cv_version", "pua_table_pin", "pin",
    "references", "codepoints", "groups", "src_w", "cos_iou_min"})
#: 组配置 `params.<步>.` 下不许写的字段：逐书看图／逐书对照定的数据（字对、码位规则、页钉、卷题正则、版式槽位）
FORBIDDEN_GROUP_PARAMS = frozenset({
    "follow_ref", "follow_ref_seen", "pua_rules", "page_pins", "coord_title_formula",
    "layout_prior", "roster_ref_corpus", "roster_ref_pins"})
_GROUP_NAME = __import__("re").compile(r"^[a-z][a-z0-9_]*$")


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


def parse_group_ref(v, where: str = "groups.config") -> tuple[str, int]:
    """`"wyg@1"` → ("wyg", 1)；别的写法报错（不猜）。"""
    s = str(v or "").strip()
    name, sep, ver = s.partition("@")
    if not sep or not _GROUP_NAME.match(name) or not ver.lstrip("v").isdigit() or int(ver.lstrip("v")) < 1:
        raise BookConfigError(f"{where} 要写成 <组名>@<版本>（如 wyg@1），收到 {v!r}")
    return name, int(ver.lstrip("v"))


def book_groups(defaults: dict) -> dict[str, object]:
    """基础配置里的 `groups:` 解析结果：`{"config": ("wyg", 1) 或 None, "glyph": [...], "corpus": [...], "model": [...]}`。
    稳定的只读取法（manager、第三步脚本用）；没写 `groups:` 返回各系统为空。"""
    g = defaults.get(GROUPS_KEY) if isinstance(defaults, dict) else None
    out: dict[str, object] = {"config": None, "glyph": [], "corpus": [], "model": []}
    if g is None:
        return out
    if not isinstance(g, dict):
        raise BookConfigError("groups: 要是映射，如 {config: wyg@1, glyph: [wyg]}")
    bad = sorted(set(g) - set(GROUP_SYSTEMS))
    if bad:
        raise BookConfigError(f"groups: 只认 {list(GROUP_SYSTEMS)}，多了 {bad}")
    if g.get("config") is not None:
        if isinstance(g["config"], (list, tuple)):
            raise BookConfigError("groups.config 只能写一个组（两个配置组互压会让顺序决定结果）")
        out["config"] = parse_group_ref(g["config"])
    for k in ("glyph", "corpus", "model"):
        v = g.get(k)
        if v is None:
            continue
        vs = [v] if isinstance(v, str) else list(v)
        for x in vs:
            if not _GROUP_NAME.match(str(x).partition("@")[0]):
                raise BookConfigError(f"groups.{k} 里的组名 {x!r} 不合规（小写字母开头，字母数字下划线）")
        out[k] = [str(x) for x in vs]
    return out


def group_ws(name: str) -> str:
    """组 `name` 在中心库的工作区名。"""
    return f"group-{name}"


def group_config_path(name: str, version: int, root: Path | None = None) -> Path:
    """组配置文件：`<root>/config/group/v<版>.yaml`；`root` 缺省为借来的只读副本 `borrowed_root('group-<组>')`。"""
    if root is None:
        from .workspace import active_branch, borrowed_root
        root = borrowed_root(group_ws(name), active_branch())
    return Path(root) / "config" / "group" / f"v{version}.yaml"


def check_group_layer(d: dict, where: str) -> None:
    """组配置里写了禁写的键就报错。"""
    bad = sorted(set(d) & FORBIDDEN_IN_GROUP)
    if bad:
        raise BookConfigError(f"{where} 里不许写 {', '.join(bad)}：身份、图源、实测先验、钉子、参校本、码位等是书或册的，不进组")
    ps = d.get("params") or {}
    if not isinstance(ps, dict):
        raise BookConfigError(f"{where} 的 params: 要是 {{step_id: {{字段: 值}}}}")
    for sid, kv in ps.items():
        if not isinstance(kv, dict):
            continue
        hit = sorted(set(kv) & FORBIDDEN_GROUP_PARAMS)
        if hit:
            raise BookConfigError(f"{where} 的 params.{sid} 里不许写 {', '.join(hit)}：逐书核定的数据留在书里")
        handling = kv.get("handling") if sid == "group_decision" else None
        if isinstance(handling, dict) and any(isinstance(h, dict) and "methods" in h for h in handling.values()):
            raise BookConfigError(f"{where} 的 params.group_decision.handling.*.methods 不许写在组里（methods 只许书里收紧）")


def load_group(name: str, version: int, root: Path | None = None) -> dict:
    """读组配置（去掉 `meta:`），查禁写键。副本缺了报错。"""
    p = group_config_path(name, version, root)
    if not p.is_file():
        raise BookConfigError(
            f"书配置钉了配置组 {name}@{version}，但本机没有 {p}：先 guji db pull（会把 {group_ws(name)} 拉成只读副本）")
    from .yaml_cache import load_yaml_cached
    d = load_yaml_cached(p) or {}
    if not isinstance(d, dict):
        raise BookConfigError(f"{p} 顶层应是映射")
    d = {k: v for k, v in d.items() if k != "meta"}
    check_group_layer(d, f"组配置 {name}@{version}（{p}）")
    return d


def effective_defaults(book_yaml_or_config_dir: Path) -> dict:
    """书级生效配置（组 ∪ 基础配置，不含册与运行覆盖）：manager 那些只认书、不认册的读者用，别再直接读 book_defaults.yaml。
    参数可以是任一册 yaml（`books/<册>.yaml`），也可以是数据目录根（含 `config/book_defaults.yaml`）。"""
    p = Path(book_yaml_or_config_dir)
    probe = p if p.suffix in (".yaml", ".yml") else p / "books" / "_.yaml"
    dflt = load_defaults(probe)
    out: dict = {}
    for _, layer in _group_layers(dflt):
        out = merge(out, layer)
    return merge(out, dflt) if dflt else out


def _group_layers(dflt: dict) -> list[tuple[str, dict]]:
    gs = book_groups(dflt)
    if gs["config"] is None:
        return []
    name, ver = gs["config"]
    return [(f"组 {name}@{ver}", load_group(name, ver))]


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
    out.extend(_group_layers(dflt))
    if dflt:
        out.append(("基础配置", dflt))
    vol = load_yaml_cached(book_yaml) or {}
    if isinstance(vol, dict) and GROUPS_KEY in vol:
        raise BookConfigError(f"{book_yaml} 里不许写 groups:：归哪个组是书的事，写在 config/book_defaults.yaml")
    out.append(("册 yaml", vol))
    if apply_override:
        ov = run_override()
        if ov:
            out.append(("运行覆盖", ov))
    return out


def _fold_admit_layer(ly: dict) -> dict:
    """每层先把收尾步参数的旧键 `seed_admit` 并成现在生效的 `char_decide`（P3a-3）：否则一层写旧键、另一层（含页型表并进来的）
    写新键，合层后两个键并存，下游 `fold_admit_params` 报「同时写了」。同一层自己两个键都写仍报错。"""
    from .decide_names import fold_admit_params
    ps = ly.get("params") if isinstance(ly, dict) else None
    if isinstance(ps, dict):
        folded = fold_admit_params(ps)
        if folded is not ps:
            return {**ly, "params": folded}
    return ly


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
        ls = [(n, _fold_admit_layer(fold_ref_profile(n, fold_layer(n, expand_layer(ly, f"{n}：")), allow_segments=(n != "基础配置" and not n.startswith("组 ")))))
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
