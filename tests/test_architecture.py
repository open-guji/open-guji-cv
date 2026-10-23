# -*- coding: utf-8 -*-
"""包分层护栏：低层包不许 import 高层包。分层与各包职责见 `doc/module_map.md`。

只做静态扫描（读 `open_guji_cv/` 的源码、解析 import），不 import 引擎，不碰任何数据。

规则：
1. 每个顶层包 / 顶层模块都必须登记在 `LAYER` 里——新增一个包就得想清它在哪一层；
2. 低层 import 高层（顶层 import 与函数内的惰性 import 都算）= 违规；
3. 已有的违规登记在 `ALLOWED_UPWARD`（2026-10-17 的存量）。**只许减不许增**：新增违规会红；
   存量修掉了而没从表里删，也会红（逼着表越来越短）。

修一条存量的办法通常是把被依赖的那段代码下沉到低层，或让调用方把依赖传进来（参数 / 回调），
不要再加一个惰性 import 绕过去——这个测试连惰性 import 也看。
注意：被 Step 声明为 `code_deps` 的文件一动，各书产物就判过期，下沉前先看 `doc/module_map.md` 末尾。
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1] / "open_guji_cv"
PKG = "open_guji_cv"

#: 层号越小越底层。同层互相 import 不限制。
LAYER: dict[str, int] = {
    # L0 基础：无内部依赖的小模块
    "errors": 0, "variants": 0, "variant_ledger": 0, "gloss": 0, "detectors": 0, "ocr": 0, "hanzi": 0,
    # L1 设施：Step 引擎、产物 schema、通用工具、格式
    "core": 1, "products": 1, "utils": 1, "formats": 1, "datastore": 1,
    # L2 算法与产出：聚类/匹配、金标、报告、渲染
    "clustering": 2, "gold": 2, "report": 2, "render": 2, "pagetype_model": 2, "groups": 2,
    # L3 管线：Step、门、影子模型、反馈事件
    "gates": 3, "steps": 3, "shadow": 3, "feedback": 3,
    # L4 应用：评测、审阅、快照、运维、实验
    "eval": 4, "review": 4, "snap": 4, "ops": 4, "exp": 4, "opinions": 4,
    # L5 控制台（Web）
    "console": 5,
    # L6 命令行入口
    "cli_v2": 6, "cli_exp": 6, "cli_glyph_db": 6, "cli_db": 6, "cli_products": 6, "cli_source": 6, "cli_opinions": 6, "cli_cellvotes": 6,
    # L7 `python -m`
    "__main__": 7,
}

#: 2026-10-17 的存量违规（低层 → 高层）。只许删，不许加。
ALLOWED_UPWARD: frozenset[str] = frozenset({
    "clustering.glyph_selfcheck -> console.routers.workspace",
    "clustering.rare_panel -> steps.align_ref",
    "clustering.rare_panel -> steps.glyph_match",
    "core.book -> review.cards",
    "core.pipeline -> steps",
    "core.step -> clustering.cnn_candidates",
    "core.step -> steps.align_ref",
    "core.step -> steps.context_decide",
    "core.step -> steps.rare_candidates",
    "feedback.lookup -> eval.colgeom",
    "feedback.vision -> review.verdict_view",
    "formats.guji_page_cv -> report.slots",
    "gates.row_segment_gate -> eval.rulers",
    "gold.store -> feedback.lock",
    "gold.transfer -> feedback.consumers",
    "gold.transfer -> feedback.routes",
    "gold.v2_align -> steps.align_ref",
    "gold.v2_align -> steps.context_decide",
    "products.fp_migrate -> clustering",
    "products.fp_migrate -> clustering.cnn_candidates",
    "products.fp_migrate -> clustering.font_candidates",
    "render.approx -> feedback.events",
    "render.overlay -> gates.query",
    "report.collate -> eval.round_check",
    "report.progress -> feedback.bindings",
    "report.progress -> feedback.lookup",
    "report.progress -> review.cards",
    "report.progress -> review.verdict_view",
    "report.tiers -> eval.round_check",
    "review.cards -> console",
    "review.cards -> console.deps",
    "utils.binarized -> clustering.normalize",
    "utils.calibrate -> steps",
    "utils.font_calibrate -> clustering.canonical",
    "utils.font_calibrate -> clustering.normalize",
    "utils.font_calibrate_direct -> clustering.canonical",
    "utils.font_calibrate_direct -> clustering.features",
    "utils.font_calibrate_direct -> clustering.font_glyphs",
    "utils.font_calibrate_direct -> clustering.normalize",
    "utils.font_calibrate_direct -> clustering.verify",
    "utils.seed_witness -> clustering.normalize",
    "utils.seed_witness -> clustering.seeding",
})


def _modules() -> dict[str, Path]:
    mods: dict[str, Path] = {}
    for p in PKG_ROOT.rglob("*.py"):
        rel = p.relative_to(PKG_ROOT.parent).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods[".".join(parts)] = p
    return mods


def _imports(mod: str, path: Path, mods: dict[str, Path]) -> set[str]:
    """`mod` import 了哪些本仓模块（含函数内的惰性 import），解析到最长的已存在模块名。"""
    is_pkg = path.name == "__init__.py"
    pkg = mod if is_pkg else mod.rsplit(".", 1)[0]
    out: set[str] = set()

    def keep(name: str) -> None:
        while name and name not in mods:
            name = name.rsplit(".", 1)[0] if "." in name else ""
        if name and name != mod:
            out.add(name)

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == PKG or a.name.startswith(PKG + "."):
                    keep(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - (node.level - 1)]
                b = ".".join(base + ([node.module] if node.module else []))
            else:
                b = node.module or ""
            if b == PKG or b.startswith(PKG + "."):
                keep(b)
                for a in node.names:
                    keep(b + "." + a.name)
    return out


def _top(mod: str) -> str:
    parts = mod.split(".")
    return parts[1] if len(parts) > 1 else ""


def _upward_edges() -> set[str]:
    mods = _modules()
    found: set[str] = set()
    for mod, path in mods.items():
        a = _top(mod)
        if a not in LAYER:
            continue
        for tgt in _imports(mod, path, mods):
            b = _top(tgt)
            if b in LAYER and LAYER[a] < LAYER[b]:
                found.add(f"{mod[len(PKG) + 1:]} -> {tgt[len(PKG) + 1:]}")
    return found


def test_every_top_level_package_has_a_layer():
    tops = {_top(m) for m in _modules() if _top(m)}
    missing = sorted(tops - set(LAYER))
    assert not missing, f"新顶层包/模块 {missing} 没登记在 LAYER 里；在 tests/test_architecture.py 和 doc/module_map.md 里给它定一层"


def test_no_new_upward_imports():
    new = sorted(_upward_edges() - ALLOWED_UPWARD)
    assert not new, "新增了低层→高层的 import（惰性 import 也算）：\n  " + "\n  ".join(new)


def test_allowlist_has_no_stale_entries():
    stale = sorted(ALLOWED_UPWARD - _upward_edges())
    assert not stale, "存量违规已经修掉了，请从 ALLOWED_UPWARD 里删掉：\n  " + "\n  ".join(stale)
