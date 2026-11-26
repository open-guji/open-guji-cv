# -*- coding: utf-8 -*-
"""止血守卫：**不许再往 `SeedAdmitParams` 加新的「字组」参数**（Mila 2026-10-17 定；零指纹成本，只加测试不动源码）。

为什么：每加一个字组就多一串扁平参数、一个 `_xxx_pass`、一套证据键／疑问码，`seed_admit.py` 越来越乱，
而且每改一次都让十册 `seed_admit` 过期。形近字组的统一接口（`open_guji_cv/groups/`）已经有了：
**新字组只许在 `groups/registry.py` 的 `GROUPS` 里登记＋配后端**，不许再往 `SeedAdmitParams` 加参数。
设计与分期见 `doc/字组/README.md`；17 个旧参数曾冻结在下面的白名单里，S6（2026-10-18）已全部删除。

规则（和 `tests/test_architecture.py` 同一种棘轮）：
1. `SeedAdmitParams` 里名字属于某个字组的字段，必须在 `ALLOWED_LEGACY` 里——新增一个就红；
2. `ALLOWED_LEGACY` 里的字段已经从 `SeedAdmitParams` 删掉了，也红（逼着白名单只会变短）。

「属于某个字组」＝名字等于某组 id 或以「<组 id>_」开头（组 id 取自注册表 `GROUPS`，所以新登记一个字组，
它的前缀自动受保护），再加两个历史前缀 `ji_yi_si`（jys 的旧名）与 `near_form`。
只做静态扫描（读 `seed_admit.py` 的语法树），不 import 引擎、不碰数据。
"""
from __future__ import annotations

import ast
from pathlib import Path

from open_guji_cv.groups import GROUPS

SRC = Path(__file__).resolve().parents[1] / "open_guji_cv" / "steps" / "seed_admit.py"

#: 历史前缀：jys 的旧名、近形家族。新字组的前缀由注册表自动给出。
LEGACY_PREFIXES = ("ji_yi_si", "near_form")

#: 2026-10-17 的存量 17 个（己已巳 `ji_yi_si_*` 10、日曰 `ry_group*` 3、入人八 `rr_clf*` 4）已于 2026-10-18
#: 并进 `group_flow` 后全部删除（方案 S6）。只许删，不许加——现在是空的，就一直空着。
ALLOWED_LEGACY: frozenset[str] = frozenset()


def _params_fields() -> list[str]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SeedAdmitParams")
    return [s.target.id for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]


def _is_group_param(name: str) -> bool:
    prefixes = tuple(GROUPS) + LEGACY_PREFIXES
    return any(name == p or name.startswith(p + "_") for p in prefixes)


def test_no_new_group_params_in_seed_admit():
    new = sorted(n for n in _params_fields() if _is_group_param(n) and n not in ALLOWED_LEGACY)
    assert not new, (
        "往 SeedAdmitParams 加了新的字组参数：" + "、".join(new) + "。\n"
        "新字组请在 open_guji_cv/groups/registry.py 的 GROUPS 里登记（成员＋后端＋策略），不要再加扁平参数、"
        "不要再写 _xxx_pass。见 doc/字组/README.md。")


def test_allowlist_has_no_stale_entries():
    fields = set(_params_fields())
    stale = sorted(ALLOWED_LEGACY - fields)
    assert not stale, "这些旧字组参数已经从 SeedAdmitParams 删掉了，请从 ALLOWED_LEGACY 里删除：" + "、".join(stale)


def test_allowlist_entries_are_group_params():
    """白名单里不许混进不属于任何字组的名字（防止借白名单偷渡别的参数）。"""
    odd = sorted(n for n in ALLOWED_LEGACY if not _is_group_param(n))
    assert not odd, f"白名单里有不属于任何字组前缀的名字：{odd}"


def test_guard_actually_detects_a_new_param():
    """守卫自检：给一个注册表里的组名加前缀的假字段，应被判为字组参数且不在白名单。"""
    for fake in ("jys_foo", "ry_new_switch", "rr_extra", "yi_560_review", "near_form_x", "ji_yi_si_other"):
        assert _is_group_param(fake) and fake not in ALLOWED_LEGACY
    for ok in ("shadow_veto", "symbol_review", "rare_ref", "lane_seal", "variant_tie"):
        assert not _is_group_param(ok)
