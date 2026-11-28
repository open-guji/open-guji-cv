"""套书（seg_set）登记：一册书的切分代码归哪一套（2026-10-30，Sheldon 定）。

一套书 = `open_guji_cv/books/<套书>/` 下自管的切分代码。册 yaml 写 `seg_set:` 指定；不写按版式推
（2026-11-28 三链合一成 `guji_default`，版式 `layout:` 取代管线 id）：grid → siku_zongmu，free → zengguang_youxue，
print → beixing。
shiji_wyg（史記文淵閣本，写本）、quantangwen（全唐文）从殿本分叉，必须在册 yaml（或工作区基础配置）里显式写。

## 套书各自的实现

套书之间不互相 import，但共用同一个 Step 壳：壳问 `resolve(book, 缺省实现模块)`，这套书有自己的实现就用它，
没有就用缺省（殿本）的。`OVERRIDES[套书]` 登记「缺省模块 → 这套书自己的模块」。同一张表也进指纹
（`engine.code_hash` 把 Step 的 `code_deps` 里被覆盖的模块换成这套书的），所以改史記的模块只让史記的产物过期，
改殿本的同名模块也不会牵动史記。本模块在 core，只放数据与字符串，不 import `books`。
"""

from __future__ import annotations

from pathlib import Path

#: cv 自带的套书＝三条版式的缺省实现。史記 shiji_wyg、全唐文 quantangwen 的代码 2026-11-09 搬去各自书仓 code/
#: （`core/book_code.py`）：工作区没有 code/ 时写这两个名字直接报错，不会悄悄走殿本的。
SEG_SETS: tuple[str, ...] = ("siku_zongmu", "zengguang_youxue", "beixing")

#: 默认链 id（2026-11-28 三链合一）与它的三个版式。
DEFAULT_CHAIN = "guji_default"
LAYOUTS: tuple[str, ...] = ("grid", "free", "print")

#: 合并前的三条链 id → 版式。永久当别名认（`core/pipeline.load_pipeline`、册配置里旧的 `pipeline:`）。
LEGACY_PIPELINES: dict[str, str] = {
    "keben_body_v2": "grid",
    "keben_free": "free",
    "modern_body": "print",
}

#: 版式 → 缺省套书（缺省实现）。
LAYOUT_SEG_SET: dict[str, str] = {
    "grid": "siku_zongmu",
    "free": "zengguang_youxue",
    "print": "beixing",
}

#: 套书 → 版式（册只写 `seg_set:` 时按它定版式，见 `layout_of`）。
SEG_SET_LAYOUT: dict[str, str] = {v: k for k, v in LAYOUT_SEG_SET.items()}

#: 兼容旧名（2026-11-28 前按管线 id 查）：旧链 id → 套书、套书 → 旧链 id。新代码用上面两张表。
PIPELINE_SEG_SET: dict[str, str] = {pid: LAYOUT_SEG_SET[lay] for pid, lay in LEGACY_PIPELINES.items()}
SEG_SET_PIPELINE: dict[str, str] = {v: k for k, v in PIPELINE_SEG_SET.items()}


def split_ref(pid: str | None) -> tuple[str | None, str | None]:
    """管线引用 → (链 id, 版式)。`guji_default@free` → (guji_default, free)；旧链 id → (guji_default, 它的版式)；
    `guji_default` → (guji_default, None)；别的 id（测试用的自造管线）→ (id, None)。"""
    if not pid:
        return None, None
    if "@" in pid:
        base, lay = pid.split("@", 1)
        if lay not in LAYOUTS:
            raise ValueError(f"管线引用 {pid!r} 的版式 {lay!r} 不认得，可选 {list(LAYOUTS)}")
        return base, lay
    if pid in LEGACY_PIPELINES:
        return DEFAULT_CHAIN, LEGACY_PIPELINES[pid]
    return pid, None


def validate_layout(name) -> str | None:
    if name is None:
        return None
    name = str(name)
    if name not in LAYOUTS:
        raise ValueError(f"layout {name!r} 不认得，可选 {list(LAYOUTS)}（core/seg_set.py）")
    return name


def layout_of(book) -> str:
    """这册书的版式（2026-11-28）：册配置 `layout:` ＞ 册里旧的 `pipeline:`（旧链 id）＞ 显式 `seg_set:` ＞
    工作区书仓 `code.yaml` 的 `base:` ＞ `edition: modern` → print ＞ grid。"""
    explicit = getattr(book, "layout", None)
    if explicit:
        return explicit
    _, lay = split_ref(getattr(book, "pipeline", None))
    if lay:
        return lay
    ss = getattr(book, "seg_set", None)
    if ss and ss in SEG_SET_LAYOUT:
        return SEG_SET_LAYOUT[ss]
    bc = _book_code()
    if bc is not None and ss in (None, bc.name):
        return bc.layout
    if getattr(book, "edition", None) == "modern":
        return "print"
    return "grid"


#: 各套书自己的缺省参数文件：`books/<套书>/defaults.yaml` 的 `params:`（形状同册配置 `params:`）。
#: 只读数据文件、不 import books（守卫 `tests/test_architecture.py`）。
BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"
IMPL_DIR = Path(__file__).resolve().parent.parent / "impl"
#: 缺省实现的三套书（2026-11-09 由 books/<套书> 改名为 impl/<版式>，套书名在册配置里照旧写）。
IMPL_OF: dict[str, str] = {"siku_zongmu": "keben", "beixing": "modern", "zengguang_youxue": "free"}


def set_dir(name: str, books_dir: Path | None = None) -> Path:
    """套书 `name` 的代码目录：缺省实现在 impl/<版式>，别的在 books/<套书>。"""
    if books_dir is not None:
        return books_dir / name
    return IMPL_DIR / IMPL_OF[name] if name in IMPL_OF else BOOKS_DIR / name

_SIKU = "open_guji_cv.impl.keben."

#: 套书 → {缺省实现模块: 这套书自己的模块}。2026-11-09 起各书的覆盖写在书仓 `code/code.yaml`（`core/book_code.py`），
#: 这张表留空只为兼容；新书别再往这里加。
OVERRIDES: dict[str, dict[str, str]] = {}


def _book_code():
    """当前工作区的书级代码（`core/book_code.py`，书仓 `code/`）；没有 → None。"""
    from .book_code import load
    return load()


def _book_code_for(name: str | None):
    """套书名 `name` 对应的书级代码：当前工作区有 `code/` 且名字相同（或册没写 seg_set）才算。"""
    bc = _book_code()
    if bc is None:
        return None
    return bc if (name is None or name == bc.name) else None


def validate_seg_set(name: str | None) -> str | None:
    if name is not None and name not in SEG_SETS:
        bc = _book_code()
        if bc is not None and bc.name == name:
            return name                 # 书仓 code/ 自带的套书（2026-11-09 书级代码）
        raise ValueError(f"seg_set {name!r} 不在登记表里，可选 {list(SEG_SETS)}（core/seg_set.py），"
                         f"也不是本工作区 code/code.yaml 的 name")
    return name


def seg_set_of(book) -> str:
    """这册书的套书：册 yaml 显式写的优先，否则按管线推。"""
    explicit = getattr(book, "seg_set", None)
    if explicit:
        return explicit
    bc = _book_code()
    if bc is not None:
        return bc.name                  # 册没写 seg_set、工作区有书级代码：归书级代码
    return LAYOUT_SEG_SET.get(layout_of(book), "siku_zongmu")


def seg_set_for_run(book, pipeline_id: str | None, layout: str | None = None) -> str:
    """跑这一趟用哪套书的缺省参数：册 yaml 显式写的 `seg_set:` 优先；否则按**这趟跑的版式**推
    （CLI 写 `keben_free`、`guji_default@print` 换了版式就跟着换），推不出再按册本身（`seg_set_of`）。
    `layout` 不给就从 `pipeline_id` 里解（旧链 id 或 `链@版式`）。"""
    explicit = getattr(book, "seg_set", None)
    if explicit:
        return explicit
    if layout is None:
        _, layout = split_ref(pipeline_id)
    bc = _book_code()
    if bc is not None and (layout is None or layout == bc.layout):
        return bc.name
    if layout in LAYOUT_SEG_SET:
        return LAYOUT_SEG_SET[layout]
    return seg_set_of(book)


def seg_set_params(name: str | None, books_dir: Path | None = None) -> dict[str, dict]:
    """套书缺省参数 `{step_id: {字段: 值}}`；没有 defaults.yaml 或没写 `params:` 返回空。

    参数层（低 → 高）：Step 默认 < 管线 yaml `params:` < **套书缺省** < 册配置 `params:` < 运行覆盖
    （`core/pipeline.base_param_layers`、`Engine.__init__`）。"""
    if not name:
        return {}
    bc = _book_code_for(name) if books_dir is None else None
    if bc is not None:
        # 书级代码：参数缺省跟代码走，读书仓 code/defaults.yaml；没有就退回 cv 里同名套书的（迁移过渡），再没有就空
        path = bc.root / "defaults.yaml"
        if not path.is_file():
            path = set_dir(name) / "defaults.yaml"
    else:
        path = set_dir(name, books_dir) / "defaults.yaml"
    if not path.is_file():
        return {}
    from .yaml_cache import load_yaml_cached
    d = load_yaml_cached(path) or {}
    raw = d.get("params") or {}
    if not isinstance(raw, dict) or any(not isinstance(v, dict) for v in raw.values()):
        raise ValueError(f"{path} 的 params: 必须是 {{step_id: {{字段: 值}}}}")
    return {str(k): dict(v) for k, v in raw.items()}


def resolve(book, default_module: str) -> str:
    """这册书在 `default_module` 这个位置该用哪个模块：套书有覆盖用覆盖，否则用缺省。"""
    ss = seg_set_of(book)
    bc = _book_code_for(ss)
    if bc is not None and default_module in bc.overrides:
        return bc.overrides[default_module]          # 书仓 code/ 的覆盖优先
    ov = OVERRIDES.get(ss)
    return ov.get(default_module, default_module) if ov else default_module


def replace_deps(book, mods: list[str]) -> list[str]:
    """指纹用：把 Step 的模块表里被这册套书覆盖的模块换成套书自己的（顺序不变）。"""
    return [resolve(book, m) for m in mods]
