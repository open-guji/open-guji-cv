"""X5 配置键归层登记（core/config_keys.py）：与 book_config 的硬规矩不打架；警告与收敛提示。"""
from __future__ import annotations

import pytest
import yaml

from open_guji_cv.core import book_config as bc
from open_guji_cv.core import config_keys as ck


def test_registry_agrees_with_hard_rules():
    for k, r in ck.KEY_RULES.items():
        assert r.recommended <= r.allowed, k
        assert r.allowed <= set(ck.LAYERS), k
        if k in bc.FORBIDDEN_IN_DEFAULTS:
            assert ck.BOOK not in r.allowed, f"{k} 基础配置里禁写，登记表却许书层"
        if k in bc.FORBIDDEN_IN_GROUP:
            assert ck.GROUP not in r.allowed, f"{k} 组里禁写，登记表却许组层"
        if k in bc.FORBIDDEN_IN_OVERRIDE:
            assert ck.RUN not in r.allowed, f"{k} 运行覆盖禁写，登记表却许运行层"
    for k, r in ck.PARAM_RULES.items():
        assert r.recommended <= r.allowed, k
        if k.split(".", 1)[1] in bc.FORBIDDEN_GROUP_PARAMS:
            assert ck.GROUP not in r.allowed, f"{k} 组里禁写，登记表却许组层"


def test_hard_rule_keys_all_registered():
    """book_config 里拦的顶层键都要进登记表（groups 之外的身份、实测键）。"""
    for k in bc.FORBIDDEN_IN_DEFAULTS | bc.VOLUME_ID_KEYS:
        assert k in ck.KEY_RULES, k


def test_layer_names():
    assert ck.layer_of("组 wyg@1") == ck.GROUP
    assert ck.layer_of("基础配置") == ck.BOOK
    assert ck.layer_of("册 yaml") == ck.VOLUME
    assert ck.layer_of("运行覆盖") == ck.RUN
    assert ck.layer_of("别的") is None


def test_check_warns_wrong_and_unrecommended_layer():
    w = ck.check([
        ("基础配置", {"corpus": 3, "params": {"align_ref": {"coord_dp": True}}}),
        ("册 yaml", {"params": {"seed_admit": {"follow_ref": "a=b"}, "align_ref": {"coord_dp": True}}}),
        ("运行覆盖", {"groups": {"config": "wyg@1"}}),
    ])
    text = "\n".join(w)
    assert "基础配置：corpus 推荐写在 册" in text
    assert "册 yaml：char_decide.follow_ref 推荐写在 书" in text          # 旧名 seed_admit 按 char_decide 登
    assert "册 yaml：align_ref.coord_dp 推荐写在 组、书" in text
    assert "运行覆盖：groups 不该写在运行层" in text
    assert not any("基础配置：align_ref.coord_dp" in x for x in w)


def test_unregistered_keys_are_quiet():
    assert ck.check([("册 yaml", {"whatever": 1, "params": {"x": {"y": 2}}})]) == []


def test_same_layer_groups():
    w = ck.check([("组 wyg@1", {"params": {"glyph_match": {"sim_model": "m"}}}),
                  ("基础配置", {"params": {"glyph_match": {"pair_clf": "p"}}})])
    assert any("要写在同一层" in x for x in w)
    w = ck.check([("基础配置", {"params": {"glyph_match": {"sim_model": "m", "pair_clf": "p"}}})])
    assert not any("要写在同一层" in x for x in w)


def test_converge_hints(tmp_path):
    for i in range(10):
        d = {"id": f"{i:02d}", "title": f"册{i}", "params": {"align_ref": {"coord_dp": True}}}
        if i < 9:
            d["iron_gate"] = True
        (tmp_path / f"{i:02d}.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    h = ck.converge_hints(tmp_path)
    assert any(x.startswith("align_ref.coord_dp = true 写在 10/10") for x in h)
    assert any(x.startswith("iron_gate = true 写在 9/10") for x in h)
    assert not any(x.startswith("id ") or x.startswith("title ") for x in h)   # 册身份不提示
    assert ck.converge_hints(tmp_path, ratio=0.95) and not any(x.startswith("iron_gate") for x in ck.converge_hints(tmp_path, ratio=0.95))


@pytest.mark.parametrize("n", [0, 1])
def test_converge_hints_needs_two_volumes(tmp_path, n):
    for i in range(n):
        (tmp_path / f"{i}.yaml").write_text("a: 1\n", encoding="utf-8")
    assert ck.converge_hints(tmp_path) == []
