# -*- coding: utf-8 -*-
"""Step 指纹覆盖守卫：Step 模块 import 的本仓模块要么在 `code_deps` 里，要么在下面登记了为什么不进。

`core/engine.py::code_hash` 只哈希 Step 自己的模块与 `spec.code_deps` 里**手列**的模块，不顺着 import 走。
Step 模块 import 了一个算法模块却没列进 `code_deps`，那个模块改了算法，各册产物照报「新鲜」、不重算——
指纹漏判，比多判过期更难发现（10-23 A20 普查时存量 11 个 Step 共 39 处）。

本测试只看 Step 模块自己的 import（含函数里的惰性 import），不看 `code_deps` 模块再往下 import 的东西。
新加的 import 必须二选一：
- 影响产物 → 列进 `code_deps`（本步 `code_hash` 随之变，各册这一步判过期，按 L 级写进 PR）；
- 不影响产物（只读路径、算库指纹、读图）→ 登进 `NOT_IN_FP`，写一句理由。

`EXISTING_GAPS` 是存量：多半影响产物，但现在补进 `code_deps` 会让那一步各册整体过期。
约定**搭车补**：哪一步下次本来就要改算法（`code_hash` 本来就要变）时，顺手把它的存量补进 `code_deps`
并从这里删掉，不额外多一次全量重跑。表只许减不许加。
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from pathlib import Path

import open_guji_cv.steps  # noqa: F401  —— 注册全部 Step
from open_guji_cv.core.step import STEPS

#: 框架层，进指纹的是 Step 本身对它们的用法，不单列
_FRAMEWORK = ("open_guji_cv.core", "open_guji_cv.products", "open_guji_cv.formats", "open_guji_cv.errors")

#: 不影响产物、不进指纹的 import：(Step 模块, 被 import 模块) → 理由
NOT_IN_FP: dict[tuple[str, str], str] = {
    ("open_guji_cv.steps.seal_detect", "open_guji_cv.utils.image_io"): "只读图",
    ("open_guji_cv.steps.seed_admit", "open_guji_cv.utils.image_io"): "只读图",
    ("open_guji_cv.steps.invert_detect", "open_guji_cv.utils.preclean"): "只解析预处理后的原图路径",
    ("open_guji_cv.steps.border_detect", "open_guji_cv.feedback.lookup"):
        "只读人裁逐列抬头（head-raise-columns）；裁决不进指纹、靠该页显式重跑生效，同 row_segment 读 manual-cells（#706）",
    ("open_guji_cv.steps.row_segment", "open_guji_cv.steps.context_decide"):
        "只借 corpus_fingerprint 算整理本文件指纹（roster_ref_fingerprint 进参数指纹），不影响切分",
}

#: 存量缺口（2026-10-23 普查）：搭车补，只减不加。
EXISTING_GAPS: dict[str, set[str]] = {
    "open_guji_cv.gates.border_detect_gate": {
        "open_guji_cv.pagetype_model.gate",
        "open_guji_cv.pagetype_model.model",
    },
    "open_guji_cv.gates.column_gate": {
        "open_guji_cv.books.siku_zongmu.jiazhu_split",
    },
    "open_guji_cv.steps.align_ref": {
        "open_guji_cv.clustering.align_eval",
        "open_guji_cv.steps.context_decide",
        "open_guji_cv.utils.cjk_compat",
        "open_guji_cv.variants",
    },
    "open_guji_cv.steps.cell_shrink": {
        "open_guji_cv.steps._warpmap",
        "open_guji_cv.steps.seed_admit",
    },
    "open_guji_cv.steps.column_crop": {
        "open_guji_cv.steps.column_warp",
    },
    "open_guji_cv.steps.context_decide": {
        "open_guji_cv.clustering.llm_context",
        "open_guji_cv.clustering.seeding",
        "open_guji_cv.clustering.variants",
        "open_guji_cv.steps.align_ref",
    },
    "open_guji_cv.steps.glyph_match": {
        "open_guji_cv.clustering.glyph_db",
        "open_guji_cv.clustering.near_shape",
        "open_guji_cv.clustering.seeding",
        "open_guji_cv.groups.registry",
    },
    "open_guji_cv.steps.rare_candidates": {
        "open_guji_cv.clustering.glyph_fp",
        "open_guji_cv.steps.align_ref",
    },
    "open_guji_cv.steps.row_segment": {
        "open_guji_cv.feedback.lookup",
        "open_guji_cv.steps._warpmap",
        "open_guji_cv.steps.glyph_match",
    },
    "open_guji_cv.steps.row_segment_runs": {
        "open_guji_cv.steps._warpmap",
    },
    "open_guji_cv.steps.seed_admit": {
        "open_guji_cv.clustering.confusable",
        "open_guji_cv.clustering.exclusions",
        "open_guji_cv.clustering.glyph_db",
        "open_guji_cv.clustering.glyph_fp",
        "open_guji_cv.clustering.normalize",
        "open_guji_cv.feedback.bindings",
        "open_guji_cv.feedback.lookup",
        "open_guji_cv.feedback.mojibake",
        "open_guji_cv.hanzi.symbols",
        "open_guji_cv.shadow.gate",
        "open_guji_cv.shadow.model",
        "open_guji_cv.shadow.signals",
        "open_guji_cv.steps.align_ref",
        "open_guji_cv.steps.context_decide",
        "open_guji_cv.utils.ji_yi_si",
    },
}


def _imports(mod_name: str) -> set[str]:
    mod = importlib.import_module(mod_name)
    path = Path(inspect.getsourcefile(mod))
    pkg = mod_name if path.name == "__init__.py" else mod_name.rpartition(".")[0]
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name.startswith("open_guji_cv")}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = pkg.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if not base.startswith("open_guji_cv"):
                continue
            for a in node.names:                 # `from ..steps import align_ref` 这种拿的是子模块
                sub = f"{base}.{a.name}"
                out.add(sub if _is_pkg(base) and importlib.util.find_spec(sub) else base)
    return {m for m in out if m != mod_name and not m.startswith(_FRAMEWORK) and m != "open_guji_cv"}


def _is_pkg(name: str) -> bool:
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        return False
    return bool(spec and spec.submodule_search_locations)


def _gaps() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for st in STEPS.values():
        m = type(st).__module__
        if not m.startswith("open_guji_cv."):    # 别的测试往 STEPS 里注册的假 Step（全量跑时才在）
            continue
        miss = {i for i in _imports(m) - set(st.spec.code_deps) if (m, i) not in NOT_IN_FP}
        if miss:
            out.setdefault(m, set()).update(miss)
    return out


def test_step_imports_are_fingerprinted_or_explained():
    new = {m: sorted(miss - EXISTING_GAPS.get(m, set())) for m, miss in _gaps().items()}
    new = {m: v for m, v in new.items() if v}
    assert not new, ("这些 Step import 的模块既不在 code_deps 也没登记理由（改了它产物照报新鲜）：\n"
                     + "\n".join(f"  {m}: {v}" for m, v in sorted(new.items())))


def test_existing_gaps_only_shrink():
    """补进 code_deps 或删了 import 之后，把对应条目从 EXISTING_GAPS 删掉，免得表里留死条目。"""
    cur = _gaps()
    stale = {m: sorted(v - cur.get(m, set())) for m, v in EXISTING_GAPS.items()}
    stale = {m: v for m, v in stale.items() if v}
    assert not stale, f"EXISTING_GAPS 里这些已经不缺了，删掉：{stale}"


def test_not_in_fp_entries_are_live():
    for (m, i), why in NOT_IN_FP.items():
        assert why.strip()
        assert i in _imports(m), f"{m} 已不 import {i}，删掉这条 NOT_IN_FP"
