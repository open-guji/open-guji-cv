"""套书（seg_set）登记：一册书的切分代码归哪一套（2026-10-30，Sheldon 定）。

一套书 = `open_guji_cv/books/<套书>/` 下自管的切分代码。册 yaml 写 `seg_set:` 指定；不写按管线推：
keben_body_v2 → siku_zongmu，keben_free → zengguang_youxue，modern_body → beixing。
shiji_wyg（史記文淵閣本，写本）、quantangwen（全唐文）从殿本分叉，必须在册 yaml（或工作区基础配置）里显式写。

## 套书各自的实现

套书之间不互相 import，但共用同一个 Step 壳：壳问 `resolve(book, 缺省实现模块)`，这套书有自己的实现就用它，
没有就用缺省（殿本）的。`OVERRIDES[套书]` 登记「缺省模块 → 这套书自己的模块」。同一张表也进指纹
（`engine.code_hash` 把 Step 的 `code_deps` 里被覆盖的模块换成这套书的），所以改史記的模块只让史記的产物过期，
改殿本的同名模块也不会牵动史記。本模块在 core，只放数据与字符串，不 import `books`。
"""

from __future__ import annotations

from pathlib import Path

SEG_SETS: tuple[str, ...] = ("siku_zongmu", "shiji_wyg", "zengguang_youxue", "beixing", "quantangwen")

PIPELINE_SEG_SET: dict[str, str] = {
    "keben_body_v2": "siku_zongmu",
    "keben_free": "zengguang_youxue",
    "modern_body": "beixing",
}

#: 套书 → 缺省走的管线（册 yaml 只写 `seg_set:` 时按它选管线，见 `core/pipeline.default_pipeline_id`）。
#: 2026-11-03 管线重组方案 B 第一期：选管线以套书为准，`pipeline:` 只为兼容旧册 yaml 留着。
SEG_SET_PIPELINE: dict[str, str] = {
    "siku_zongmu": "keben_body_v2",
    "shiji_wyg": "keben_body_v2",
    "quantangwen": "keben_body_v2",
    "zengguang_youxue": "keben_free",
    "beixing": "modern_body",
}

#: 各套书自己的缺省参数文件：`books/<套书>/defaults.yaml` 的 `params:`（形状同册配置 `params:`）。
#: 只读数据文件、不 import books（守卫 `tests/test_architecture.py`）。
BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"

_SIKU = "open_guji_cv.books.siku_zongmu."
_SJ = "open_guji_cv.books.shiji_wyg."
_QTW = "open_guji_cv.books.quantangwen."

#: 套书 → {缺省实现模块: 这套书自己的模块}。史記是从殿本分叉出来的写本：先只分叉职名页（臣行拆分等写本专用逻辑），
#: 别的步骤仍走缺省实现；以后哪一步要为写本改，就把那个模块复制进 books/shiji_wyg/ 再登记在这里。
OVERRIDES: dict[str, dict[str, str]] = {
    "shiji_wyg": {
        _SIKU + "roster_segment": _SJ + "roster_segment",
        _SIKU + "roster_glyph": _SJ + "roster_glyph",
        _SIKU + "jiazhu_step": _SJ + "jiazhu_step",
    },
    # 全唐文（嘉慶內府本）：2026-11-04 从殿本分叉 Step3 行切分（row_boundaries＋jiazhu_split），
    # 放全唐文专用的「一行就完的雙行小注」等；别的步骤仍走殿本的。册配置写 `seg_set: quantangwen`。
    "quantangwen": {
        _SIKU + "row_boundaries": _QTW + "row_boundaries",
        _SIKU + "jiazhu_split": _QTW + "jiazhu_split",
    },
}


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
    pid = getattr(book, "pipeline", None)
    if not pid:
        f = getattr(book, "default_pipeline_id", None)
        pid = f() if callable(f) else None
    return PIPELINE_SEG_SET.get(pid, "siku_zongmu")


def seg_set_for_run(book, pipeline_id: str | None) -> str:
    """跑这一趟用哪套书的缺省参数：册 yaml 显式写的 `seg_set:` 优先；否则按**这趟跑的管线**推
    （CLI `--pipeline` 换了管线就跟着换），推不出再按册本身（`seg_set_of`）。"""
    explicit = getattr(book, "seg_set", None)
    if explicit:
        return explicit
    bc = _book_code()
    if bc is not None and (not pipeline_id or pipeline_id == bc.pipeline):
        return bc.name
    if pipeline_id and pipeline_id in PIPELINE_SEG_SET:
        return PIPELINE_SEG_SET[pipeline_id]
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
            path = BOOKS_DIR / name / "defaults.yaml"
    else:
        path = (books_dir or BOOKS_DIR) / name / "defaults.yaml"
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
