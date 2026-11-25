"""页型表 `page_kinds`（册配置顶层字段，2026-11-04 页型表第 1 步）。

册 yaml 里一张表说清「哪些页是什么页」：

    page_kinds:
      body:   [88, 90]       # 页型规则判错、强制按正文切
      table:  ["8-163"]      # 表格页，整页跳过
    cover:  [1]            # 书衣／封面页，整页跳过（页型记 cover）
      roster: ["89-132"]     # 职名页，走职名页分支
      no_ref: ["5-7"]        # 无参校本页：参校本里本来就没有这段（序、牒文），照常切、对位，放行换 seed_admit.no_ref_params 那套
      table_cols:            # 半文半表页：本页这些列是表、跳过，其余列按正文切、对位（GUJI-772，2026-11-16）
        112: ["1-5"]         # {页: [列号…]}，列号同产物 col（图上右起第几列，从 1 起；产物 quad 右上原点），写法同页号
      roster_cols:           # 正文页里夹的职名列：本页这些列走职名页分支（不定字数），其余列照正文切（2026-11-19，《脉经》）
        11: [2]              # 写法同 table_cols

读配置时（`BookSpec.__post_init__`）把它翻成原来就有的三个 Step 参数，**值一字不改**，所以 Step 参数指纹、
各步产物都不变（L0）：

    body   → params.border_detect_gate.body_pages
    table  → params.border_detect_gate.table_pages
    cover  → params.border_detect_gate.cover_pages   （2026-11-04 加：书衣／封面，整页跳过，网站出占位）
    roster → params.row_segment.roster_pages
    no_ref → params.seed_admit.no_ref_pages      （2026-11-19 加：无参校本页，配书级 `seed_admit.no_ref_params` 换放行参数）
    table_cols → params.column_gate.table_cols   （2026-11-16 加，GUJI-772：页内按列标表；新参数，没有老写法）
    roster_cols → params.row_segment.roster_cols （2026-11-19 加：页内按列标职名列；新参数，没有老写法）

`table_cols` 不是「一类页」而是「页里哪几列」，值是 `{页: [列号…]}` 不是页号表，所以不在 `KIND_PARAM`／`PAGE_KINDS`
里（读页型表的人照旧拿到 `{页型: [页号…]}`），另有 `TABLE_COLS`／`table_cols_from_params`。同一页不许既整页 table
（或 cover）又按列 table_cols。`roster_cols` 同形（`COL_KINDS` 登记两者）：同一页不许既整页 roster／table／cover
又按列 roster_cols，同一列不许既 table_cols 又 roster_cols。
老写法照旧能用。同一类页不许新老两处同时写不同的值（报错，不猜谁生效）；两处写的值一样不算冲突，所以
`dataclasses.replace` 出的副本（`__post_init__` 再跑一遍）不会误报。
页号写法同 `_expand_pages`：整数，或 `"10-380"`、`"3,9,12-15"` 这类字符串。

本模块在 core，只放数据与纯函数，不 import steps／books。不在任何 Step 的 `code_deps` 里。
"""
from __future__ import annotations

#: 页型 → (Step id, 参数名)。顺序即文档与报表里的显示顺序。
KIND_PARAM: dict[str, tuple[str, str]] = {
    "body": ("border_detect_gate", "body_pages"),
    "table": ("border_detect_gate", "table_pages"),
    "cover": ("border_detect_gate", "cover_pages"),
    "roster": ("row_segment", "roster_pages"),
    "no_ref": ("seed_admit", "no_ref_pages"),
}
PAGE_KINDS = tuple(KIND_PARAM)
#: 页内按列标表（半文半表页）：键名与 (Step id, 参数名)
TABLE_COLS = "table_cols"
TABLE_COLS_PARAM: tuple[str, str] = ("column_gate", "table_cols")
#: 页内按列标职名列（正文页里夹的一两列职名，《脉经》各卷卷端「朝散大夫……臣林億等類次」，2026-11-19）
ROSTER_COLS = "roster_cols"
ROSTER_COLS_PARAM: tuple[str, str] = ("row_segment", "roster_cols")
#: 按列的页型：键名 → (Step id, 参数名)。值都是 `{页: [列号…]}`
COL_KINDS: dict[str, tuple[str, str]] = {TABLE_COLS: TABLE_COLS_PARAM, ROSTER_COLS: ROSTER_COLS_PARAM}


def _load_table_cols(raw, kind: str = TABLE_COLS) -> dict[int, list]:
    """`table_cols／roster_cols: {页: [列号…]}` → `{int 页: [升序列号…]}`（按页排序）。列号写法同页号（整数或 "1-5"），页键只收单页整数。"""
    from .book import _expand_pages
    if not isinstance(raw, dict):
        raise ValueError(f"page_kinds.{kind}: 要写成 {{页: [列号…]}}，如 {{112: [\"1-5\"]}}")
    out: dict[int, list] = {}
    for pg, cols in raw.items():
        try:
            if isinstance(pg, bool):
                raise ValueError
            page = int(str(pg).strip())
        except ValueError:
            raise ValueError(f"page_kinds.{kind}: 页号 {pg!r} 要是整数（一页一条）") from None
        if cols is None:
            continue
        if isinstance(cols, (int, str)):
            cols = [cols]
        if not isinstance(cols, (list, tuple)) or any(isinstance(c, bool) or not isinstance(c, (int, str)) for c in cols):
            raise ValueError(f"page_kinds.{kind}.{page}: 要写成列号列表（整数或 \"1-5\" 这样的字符串）")
        try:
            got = _expand_pages(list(cols))
        except ValueError as e:
            raise ValueError(f"page_kinds.{kind}.{page}: 列号写错了：{e}") from None
        if any(c < 1 for c in got):
            raise ValueError(f"page_kinds.{kind}.{page}: 列号从 1 起（图上右起第几列）")
        if got:
            out[page] = sorted(set(got))       # 展开成升序整数：["1-3"] 与 [1, 2, 3] 同一个指纹
    return dict(sorted(out.items()))


def _expand_cols(cols) -> list[int]:
    from .book import _expand_pages
    return _expand_pages([cols] if isinstance(cols, (int, str)) else list(cols))


def load_page_kinds(raw) -> dict[str, list]:
    """yaml 的 `page_kinds:` → `{页型: [页号表达式…]}`。形状错、页型名错、页号写错都在读配置时报。
    空表达式的页型（`body: []` 或 `null`）整条去掉；页号原样保留（不展开），展开交给用到它的 Step。"""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("page_kinds: 必须是 {页型: [页号…]}，页型是 " + "、".join(PAGE_KINDS))
    from .book import _expand_pages
    out: dict[str, list] = {}
    for kind, pages in raw.items():
        kind = str(kind)
        if kind in COL_KINDS:
            tc = _load_table_cols(pages, kind) if pages is not None else {}
            if tc:
                out[kind] = tc
            continue
        if kind not in KIND_PARAM:
            raise ValueError(f"page_kinds: 未知页型 {kind!r}，只认 {'、'.join(PAGE_KINDS + tuple(COL_KINDS))}")
        if pages is None:
            continue
        if isinstance(pages, (int, str)):
            pages = [pages]
        if not isinstance(pages, (list, tuple)) or any(isinstance(p, bool) or not isinstance(p, (int, str)) for p in pages):
            raise ValueError(f"page_kinds.{kind}: 要写成页号列表（整数或 \"10-380\" 这样的字符串）")
        try:
            _expand_pages(list(pages))
        except ValueError as e:
            raise ValueError(f"page_kinds.{kind}: 页号写错了：{e}") from None
        if pages:
            out[kind] = list(pages)
    # 封面页不许同时点名成别的页型（新页型，没有历史包袱；body 与 table 同页的老配置照旧放行，闸里表格优先）
    if "cover" in out:
        cov = set(_expand_pages(out["cover"]))
        for kind in ("body", "table"):
            both = sorted(cov & set(_expand_pages(out.get(kind) or [])))
            if both:
                raise ValueError(f"page_kinds: 第 {both[0]} 页同时写在 cover 和 {kind} 里，一页只能是一种页型")
    if TABLE_COLS in out:
        for kind in ("table", "cover"):
            both = sorted(set(out[TABLE_COLS]) & set(_expand_pages(out.get(kind) or [])))
            if both:
                raise ValueError(f"page_kinds: 第 {both[0]} 页既整页写在 {kind} 里、又在 table_cols 里按列标表，二者选一")
    if ROSTER_COLS in out:
        for kind in ("roster", "table", "cover"):
            both = sorted(set(out[ROSTER_COLS]) & set(_expand_pages(out.get(kind) or [])))
            if both:
                raise ValueError(f"page_kinds: 第 {both[0]} 页既整页写在 {kind} 里、又在 roster_cols 里按列标职名列，二者选一")
        for pg in sorted(set(out[ROSTER_COLS]) & set(out.get(TABLE_COLS) or {})):
            both = sorted(set(out[ROSTER_COLS][pg]) & set(out[TABLE_COLS][pg]))
            if both:
                raise ValueError(f"page_kinds: 第 {pg} 页第 {both[0]} 列同时写在 table_cols 和 roster_cols 里，一列只能是一种")
    return out


def to_params(page_kinds: dict[str, list] | None) -> dict[str, dict]:
    """`{页型: [页号…]}` → `{step_id: {参数名: [页号…]}}`（只含写了的页型）。"""
    out: dict[str, dict] = {}
    for kind, pages in (page_kinds or {}).items():
        if kind in COL_KINDS:
            sid, field = COL_KINDS[kind]
            out.setdefault(sid, {})[field] = {int(pg): sorted(set(_expand_cols(c))) for pg, c in pages.items()}
            continue
        sid, field = KIND_PARAM[kind]
        out.setdefault(sid, {})[field] = list(pages)
    return out


def merge_into_params(params: dict[str, dict], page_kinds: dict[str, list] | None) -> dict[str, dict]:
    """把页型表并进册配置 `params`（返回新字典，不改入参）。

    `params` 里同一个字段已经有**不同**的非空值 → 报错；值相同或老字段是空／null → 用页型表的。"""
    tr = to_params(page_kinds)
    if not tr:
        return params
    out = {sid: dict(kv) for sid, kv in (params or {}).items()}
    for sid, kv in tr.items():
        for field, pages in kv.items():
            old = out.get(sid, {}).get(field)
            if isinstance(pages, dict):
                same = old in (None, {}) or {int(k): sorted(set(_expand_cols(v))) for k, v in dict(old).items()} == pages
            else:
                same = old in (None, [], ()) or list(old) == pages
            if not same:
                kind = next((k for k, v in {**KIND_PARAM, **COL_KINDS}.items() if v == (sid, field)), TABLE_COLS)
                raise ValueError(
                    f"page_kinds.{kind} 和 params.{sid}.{field} 两处都写了、值不一样（{pages} / {old if isinstance(old, dict) else list(old)}）："
                    f"同一类页只写一处，新写法用 page_kinds")
            out.setdefault(sid, {})[field] = pages
    return out


def kinds_from_params(params: dict[str, dict] | None) -> dict[str, list]:
    """反过来：从（已合并的）`params` 里读出三个字段，得到生效的页型表。不管用户写的是新写法还是老写法，
    `BookSpec.page_kinds` 都是这张表——给 `guji pagekinds` 之类读的人用，不必再各自去三个 Step 参数里找。"""
    out: dict[str, list] = {}
    for kind, (sid, field) in KIND_PARAM.items():
        sp = (params or {}).get(sid)
        v = sp.get(field) if isinstance(sp, dict) else None     # 形状错的 params 交给后面的校验报
        if v not in (None, [], ()):
            out[kind] = list(v)
    return out


def table_cols_from_params(params: dict[str, dict] | None, kind: str = TABLE_COLS) -> dict[int, list]:
    """从（已合并的）`params` 读生效的 `table_cols`（或 `kind` 指的别的按列页型）：`{页: [升序列号…]}`，没写返回空。"""
    sid, field = COL_KINDS[kind]
    v = ((params or {}).get(sid) or {}).get(field)
    return {int(k): sorted(set(_expand_cols(c))) for k, c in dict(v).items() if c} if v else {}


def fold_layer(name: str, layer: dict) -> dict:
    """一层配置里的 `page_kinds` 翻进它自己的 `params`（返回新字典，去掉 `page_kinds` 键）。

    逐层先翻再叠：高层（运行覆盖）写老写法也能盖掉低层（册 yaml）的页型表，同层两处写不同的值报错（带层名）。
    这层没写 `page_kinds` 就原样返回。"""
    if not layer.get("page_kinds"):
        return layer
    try:
        params = merge_into_params(layer.get("params") or {}, load_page_kinds(layer["page_kinds"]))
    except ValueError as e:
        raise ValueError(f"{name}：{e}") from None
    out = {k: v for k, v in layer.items() if k != "page_kinds"}
    out["params"] = params
    return out


#: 老写法登记：(Step id, 参数名) → 页型。`reject_old_syntax` 用。
_OLD = {v: k for k, v in KIND_PARAM.items()}
_OLD[TABLE_COLS_PARAM] = TABLE_COLS       # 新参数也只许经 page_kinds 写（册 yaml／基础配置直接写 params 报错，运行覆盖放行）
_OLD[ROSTER_COLS_PARAM] = ROSTER_COLS
#: 老写法 2026-11-04 起警告，2026-11-13 起报错（扫过中心库 391 册，没有册还在用）
OLD_SYNTAX_ERROR_FROM = "2026-11-13"


def old_syntax_in(layer: dict) -> list[tuple[str, str]]:
    """一层配置里还在用老写法的 [(老参数路径, 该用的 page_kinds 键)…]（空值不算）。"""
    out = []
    params = layer.get("params") if isinstance(layer, dict) else None
    for (sid, field), kind in _OLD.items():
        sub = (params or {}).get(sid) if isinstance(params, dict) else None
        if isinstance(sub, dict) and sub.get(field):
            out.append((f"params.{sid}.{field}", f"page_kinds.{kind}"))
    return out


def reject_old_syntax(book: str, name: str, layer: dict) -> None:
    """册 yaml／基础配置里写页型老写法 → 报错（2026-11-13 起；此前只警告，见 `OLD_SYNTAX_ERROR_FROM`）。
    运行覆盖里的不管：`--override` 做实验时随手写老字段是正当用法。
    环境变量 `GUJI_ALLOW_OLD_PAGE_SYNTAX=1` 放行（只发 `FutureWarning`）：迁移脚本要读迁移前的老写法册核指纹，
    手上有没迁的册也可临时用；迁移用 `python scripts/migrate_page_kinds.py <工作区>/books`。"""
    old = old_syntax_in(layer)
    if not old:
        return
    msg = (f"{book}（{name}）还在用页型老写法 {'、'.join(a for a, _ in old)}；请改写 {'、'.join(b for _, b in old)}"
           f"（python scripts/migrate_page_kinds.py <工作区>/books 干跑看改动，装 guji-manager）")
    import os
    if os.environ.get("GUJI_ALLOW_OLD_PAGE_SYNTAX") == "1":
        import warnings
        warnings.warn(msg + "；已用 GUJI_ALLOW_OLD_PAGE_SYNTAX 放行", FutureWarning, stacklevel=3)
        return
    from .book_config import BookConfigError
    raise BookConfigError(msg)
