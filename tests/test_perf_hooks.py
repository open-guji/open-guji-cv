"""步内分段计时 `cli_perf.install_hooks`：换上的计时薄壳不改结果，分段记进 perf。

壳只调原函数、原样返回；这里拿真匹配器跑一遍 glyph_match（冻结样页，库用本页自己的字块现建），
开壳与不开壳产物逐字节相同，且分段里有 `GlyphMatcher._match`。另核 `PERF_HOOKS` 点名的函数都还在
（改名了这里会红：把名单跟着改，不然那一段就悄悄不计了）。
"""

from __future__ import annotations

import importlib

import pytest

from open_guji_cv import cli_perf
from open_guji_cv.core import perf


def test_hook_names_still_exist():
    missing = []
    for modname, spec in cli_perf.PERF_HOOKS.items():
        mod = importlib.import_module(modname)
        missing += [f"{modname}.{n}" for n in spec.get("funcs", ()) if not callable(getattr(mod, n, None))]
        for cname, meths in spec.get("methods", {}).items():
            cls = getattr(mod, cname)
            missing += [f"{cname}.{n}" for n in meths if n not in cls.__dict__]
    assert not missing, f"PERF_HOOKS 点名的函数找不到了（改名？）：{missing}"


def test_install_is_reversible_and_keeps_lru_interface(monkeypatch):
    """用一个现造的模块（不碰真模块：同进程别的用例跑过 `guji step` 会已经全局套过壳）。"""
    import functools
    import sys
    import types
    monkeypatch.delenv("GUJI_PERF", raising=False)
    mod = types.ModuleType("_t_perf_hook_mod")

    @functools.lru_cache(maxsize=4)
    def f(x):
        return x * 2
    mod.f = f
    monkeypatch.setitem(sys.modules, "_t_perf_hook_mod", mod)
    hooks = {"_t_perf_hook_mod": {"funcs": ("f",)}}
    assert cli_perf.install_hooks(hooks) == ["_t_perf_hook_mod.f"]
    assert mod.f is not f and mod.f.__perf_hook__ is f
    assert cli_perf.install_hooks(hooks) == [], "不重复套壳"
    with perf.page_scope() as rec:
        assert mod.f(3) == 6
    assert rec.to_dict()["spans"]["_t_perf_hook_mod.f"][0] == 1
    mod.f.cache_clear()                       # lru_cache 的接口照旧能用
    cli_perf.uninstall_hooks(hooks)
    assert mod.f is f


def test_disabled_installs_nothing(monkeypatch):
    import sys
    import types
    monkeypatch.setenv("GUJI_PERF", "0")
    mod = types.ModuleType("_t_perf_hook_off")
    mod.g = lambda: 1
    monkeypatch.setitem(sys.modules, "_t_perf_hook_off", mod)
    assert cli_perf.install_hooks({"_t_perf_hook_off": {"funcs": ("g",)}}) == []


def test_glyph_match_same_products_with_hooks(tmp_path, monkeypatch, ws, fixture_page):
    import open_guji_cv.steps  # noqa: F401
    from helpers import run_keben_from_raw
    from open_guji_cv.clustering.match import GlyphMatcher
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.steps.glyph_match import GlyphMatchParams

    monkeypatch.delenv("GUJI_PERF", raising=False)
    bk = load_book("keben")
    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=bk, gray=fixture_page)
    chars = ctx.product("char_index", 1)
    lib = GlyphMatcher(k=5)
    n = 0
    for cc in chars.columns:
        for r in cc.chars if cc.ok else ():
            if r.cell_type == "char" and r.patch_key and n < 60:
                lib.add(f"v2:lib:{n}", "甲" if n % 2 else "乙", normalize_patch(ctx.image("char_patch", r.patch_key)))
                n += 1
    assert n >= 10, "样页没切出够多的字块"
    step = STEPS["glyph_match"]
    monkeypatch.setattr(type(step), "_matcher", lambda self, p: lib)
    ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="t", font_tier=False, batch_knn=False,
                                                 consensus_min_confirmed=0)

    cli_perf.uninstall_hooks()   # 同进程别的用例跑过 `guji step` 时已全局套过壳：先换回原函数再比
    plain = step.run_page(ctx, 1)["glyph_match"].model_dump_json()
    hooks = {k: v for k, v in cli_perf.PERF_HOOKS.items() if k != "open_guji_cv.steps.glyph_match"}
    try:
        assert cli_perf.install_hooks(hooks)
        with perf.page_scope() as rec:
            hooked = step.run_page(ctx, 1)["glyph_match"].model_dump_json()
    finally:
        cli_perf.uninstall_hooks(hooks)
    assert hooked == plain
    spans = rec.to_dict()["spans"]
    assert "GlyphMatcher._match" in spans and spans["GlyphMatcher._match"][0] >= 10
    assert "normalize.normalize_patch" in spans
    assert "GlyphMatcher._match/verify._elastic_align" in spans, sorted(spans)
