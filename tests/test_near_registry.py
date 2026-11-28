"""形近字组登记表 `near_groups/2`（W1 第一期，2026-11-28）：生成脚本的合表规则、读口、`ref` 展开，以及
「提交的 config/near_groups/v2.json 与生成脚本输出一致」的守卫。

合表规则与读口都用自造数据测；只有守卫读仓里的来源（`config/` 下的表和 `groups/registry.py`，不读活数据）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("build_near_groups_v2", REPO / "scripts" / "build_near_groups_v2.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


B = _script()


def _reg(gid, chars, typ="near", **kw):
    return {"id": gid, "chars": sorted(chars), "type": typ, "name": "".join(chars), "methods": kw.pop("methods", []), **kw}


def _p(*src, **extra):
    return {"src": set(src), **extra}


REG = [
    _reg("guan", "官宫宮", "fold", fold={"宮": "宫"}, families=["官", "宫宮"], methods=["near_p", "ctx"]),
    _reg("wm", "未末", methods=["ctx", "bars"]),
    _reg("sz", "宋朱未", methods=["ids"]),
    _reg("ce", "冊册", "variant", canon="冊", methods=["freq", "ids"]),
]


# ── 合表 ──────────────────────────────────────────────────────────────


def test_build_dedups_pairs_and_merges_src():
    t = B.build(REG, {"未末": _p("hand", "near_groups", core=True), "天夭": _p("near_groups", ng_src=["lib:qtw"]),
                      "侯𠋫": _p("near_groups", ng_src=["variant"])})
    g = t["groups"]
    assert t["format"] == "near_groups/2"
    assert g["wm"]["pairs"]["未末"]["src"] == ["hand", "near_groups"]
    assert g["wm"]["src"] == ["hand", "near_groups", "registry"]
    assert g["p:天夭"]["type"] == "near" and g["p:天夭"]["chars"] == ["天", "夭"] and g["p:天夭"]["methods"] == []
    assert g["p:侯𠋫"]["type"] == "variant"
    assert list(g)[-2:] == ["p:侯𠋫", "p:天夭"]               # 注册组在前，单立字对在后
    assert t["n_pairs"] == 3 and t["n_registry"] == 4 and t["n_pair_groups"] == 2


def test_pair_attaches_to_every_group_holding_both_chars():
    t = B.build(REG, {"宋未": _p("font", font=0.99)})
    assert "宋未" in t["groups"]["sz"]["pairs"] and "p:宋未" not in t["groups"]
    assert "宋未" not in (t["groups"]["wm"].get("pairs") or {})          # wm 只有「未」，不挂
    t = B.build([*REG, _reg("wz", "未末朱")], {"未末": _p("hand")})
    assert "未末" in t["groups"]["wm"]["pairs"] and "未末" in t["groups"]["wz"]["pairs"]


def test_build_is_deterministic_regardless_of_input_order():
    pairs = {"未末": _p("hand"), "天夭": _p("near_groups"), "冊册": _p("near_groups", ng_src=["variant"])}
    a = B.dumps(B.build(REG, pairs))
    b = B.dumps(B.build(list(reversed(REG)), dict(reversed(list(pairs.items())))))
    assert a == b


def test_book_pair_clf_and_glyph_near(tmp_path):
    pc = tmp_path / "pair_clf.json"
    pc.write_text(json.dumps({"pairs": {"官宫": {"a": "官", "b": "宫", "tier": 3}, "天夭": {"a": "天", "b": "夭", "tier": 2}},
                              "context": ["己已"]}, ensure_ascii=False), encoding="utf-8")
    gn = tmp_path / "book.yaml"
    gn.write_text("params:\n  glyph_near:\n    groups:\n      gong:\n        chars: [宫, 宮, 官]\n"
                  "        methods: {cnn_small: models/glyph_near_gong}\n        trigger: member\n", encoding="utf-8")
    t = B.build(REG, {}, {"bk": B.book_pair_clf("bk", pc)}, {"bk": B.book_glyph_near(gn)})
    g = t["groups"]
    assert g["guan"]["books"]["bk"]["pair_clf"]["pairs"] == {"官宫": 3}
    assert g["guan"]["books"]["bk"]["glyph_near"] == {"id": "gong", "methods": {"cnn_small": "models/glyph_near_gong"},
                                                     "trigger": "member"}
    assert g["p:天夭"]["src"] == ["pair_clf:bk"] and g["p:天夭"]["books"]["bk"]["pair_clf"]["pairs"] == {"天夭": 2}
    jy = B.pair_key("己", "已")
    assert g["p:" + jy]["books"]["bk"]["pair_clf"]["pairs"] == {jy: "context"}
    assert t["books"] == ["bk"]


def test_repo_pair_sources_drop_list_spares_hand_and_human(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "confusable_human.json").write_text(json.dumps({"pairs": {"甲乙": 1.0}}, ensure_ascii=False), encoding="utf-8")
    (cfg / "confusable_font_degraded.json").write_text(json.dumps({"pairs": {"丙丁": 0.99, "戊己": 0.5}}, ensure_ascii=False),
                                                       encoding="utf-8")
    (cfg / "near_groups.json").write_text(json.dumps({"pairs": {"甲乙": {"src": ["human"], "core": True},
                                                                "庚辛": {"src": ["lib:x"], "near": {"x": 0.98}}}},
                                                     ensure_ascii=False), encoding="utf-8")
    (cfg / "near_groups_drop.tsv").write_text("# 注释\n甲乙\t人裁过的不受管\n丙丁\t假对\n壬癸\t手工核过的不受管\n", encoding="utf-8")
    (cfg / "near_groups").mkdir()
    (cfg / "near_groups" / "hand.json").write_text(json.dumps({"pairs": [{"a": "曰", "b": "日"}, {"a": "壬", "b": "癸"}]},
                                                              ensure_ascii=False), encoding="utf-8")
    got = B.repo_pair_sources(tmp_path)
    k = B.pair_key
    assert got[k("甲", "乙")]["src"] == {"human", "near_groups"}
    assert k("丙", "丁") not in got and k("戊", "己") not in got  # 剔除名单／低于 τ
    assert got[k("庚", "辛")]["near"] == {"x": 0.98} and got[k("庚", "辛")]["ng_src"] == ["lib:x"]
    assert got[k("曰", "日")]["src"] == {"hand"}  # 手工表来自 <root>/config/near_groups/hand.json（第二期起不再从 confusable 读）
    assert got[k("壬", "癸")]["src"] == {"hand"}


def test_repo_pair_sources_shape_pairs(tmp_path):
    """来源 7 `shape_pairs.json`（第四步刻形判法的字对，2026-11-28）：src＝shape，剔除名单也不剔。"""
    cfg = tmp_path / "config"
    (cfg / "near_groups").mkdir(parents=True)
    for f, d in (("confusable_human.json", {"pairs": {}}), ("confusable_font_degraded.json", {"pairs": {}}),
                 ("near_groups.json", {"pairs": {"之矣": {"src": ["lib:x"]}}})):
        (cfg / f).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    (cfg / "near_groups_drop.tsv").write_text("之矣\t假对\n", encoding="utf-8")
    (cfg / "near_groups" / "hand.json").write_text(json.dumps({"pairs": []}), encoding="utf-8")
    (cfg / "near_groups" / "shape_pairs.json").write_text(json.dumps({"pairs": [{"a": "矣", "b": "之"}]}, ensure_ascii=False),
                                                         encoding="utf-8")
    got = B.repo_pair_sources(tmp_path)
    assert got["之矣"]["src"] == {"shape", "near_groups"}
    (cfg / "near_groups" / "shape_pairs.json").unlink()                  # 没这个文件：照旧（被剔除名单剔掉）
    assert "之矣" not in B.repo_pair_sources(tmp_path)


def test_type_override_for_pair_groups(tmp_path):
    """单立字对组的类型人定覆盖（Sheldon 11-28）：pair_clf 来的 侣侶 记 variant、凊淸 保持 near；成员、来源、别的组不变。"""
    ov = B.read_type_override(B.ROOT / "config" / "near_groups" / "type_override.json")
    assert ov == {"侣侶": "variant", "凊淸": "near"}
    f = tmp_path / "clf.json"
    f.write_text(json.dumps({"pairs": {"侣侶": {"a": "侣", "b": "侶", "tier": 2}, "凊淸": {"a": "凊", "b": "淸", "tier": 1},
                                       "戊庚": {"a": "戊", "b": "庚", "tier": 1}}}, ensure_ascii=False), encoding="utf-8")
    bp = {"qtw": B.book_pair_clf("qtw", f)}
    plain = B.build(REG, {}, bp)
    got = B.build(REG, {}, bp, type_override=ov)
    assert plain["groups"]["p:侣侶"]["type"] == "near" and got["groups"]["p:侣侶"]["type"] == "variant"
    assert got["groups"]["p:凊淸"]["type"] == "near" and got["groups"]["p:" + B.pair_key("戊", "庚")]["type"] == "near"
    for gid in plain["groups"]:                                         # 除 type 外逐键相同
        assert {k: v for k, v in got["groups"][gid].items() if k != "type"} == \
            {k: v for k, v in plain["groups"][gid].items() if k != "type"}
    assert got["n_by_type"] == {**plain["n_by_type"], "near": plain["n_by_type"]["near"] - 1,
                                "variant": plain["n_by_type"].get("variant", 0) + 1}
    assert B.build(REG, {}, type_override=ov) == B.build(REG, {})       # 对没进表：不起作用（仓里的表不带 pair_clf）
    bad = tmp_path / "ov.json"
    bad.write_text(json.dumps({"types": {"甲乙": "weird"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        B.read_type_override(bad)


def test_committed_v2_has_zhiyi_for_3b_only():
    """之矣 只为 3b 的 pair_shape 方法进登记表：有组 `p:之矣` 可 ref，现役护栏／对手表一个都不多。"""
    from open_guji_cv.clustering import confusable as C
    from open_guji_cv.groups import near_registry as NR
    g = NR.load().get("p:之矣")
    assert g.chars == ("之", "矣") and g.type == "near" and g.src == ("shape",)
    assert NR.load().glyph_near_spec("p:之矣") == {"chars": ["之", "矣"], "methods": {}}
    for src in ("hand", "human", "font"):
        assert ("之", "矣") not in C.registry_pairs(src)
    assert "矣" not in C.partners().get("之", frozenset())


# ── 读口 ──────────────────────────────────────────────────────────────


@pytest.fixture
def reg_path(tmp_path):
    t = B.build(REG, {"未末": _p("hand"), "天夭": _p("near_groups"), "宋未": _p("font")},
                book_gn={"bk": {"gong": {"chars": ["宫", "宮", "官"], "methods": {"cnn_small": "m/g"}, "delta": 0.05}}})
    p = tmp_path / "v2.json"
    p.write_text(B.dumps(t), encoding="utf-8")
    return p


def test_load_lookup_and_filter(reg_path):
    from open_guji_cv.groups import near_registry as NR
    reg = NR.load(reg_path)
    assert len(reg) == 5 and "guan" in reg
    assert reg.get("guan").chars == ("官", "宫", "宮") and reg.get("guan").canon("宮") == "宫"
    assert [g.id for g in reg.groups_of("未")] == ["sz", "wm"]
    assert [g.id for g in reg.groups_of("天")] == ["p:天夭"] and not reg.get("p:天夭").registered
    assert [g.id for g in reg.groups_of("宮", "fold")] == ["guan"] and reg.groups_of("宮", "near") == []
    assert {g.id for g in reg.by_type("variant")} == {"ce"}
    with pytest.raises(ValueError):
        reg.by_type("形近")
    with pytest.raises(KeyError):
        reg.get("nope")


def test_rejects_unknown_format_and_type(tmp_path):
    from open_guji_cv.groups.near_registry import NearRegistry
    with pytest.raises(ValueError):
        NearRegistry({"format": "near_groups/1", "groups": {}})
    with pytest.raises(ValueError):
        NearRegistry({"format": "near_groups/2", "groups": {"x": {"chars": ["甲", "乙"], "type": "形近"}}})


def test_glyph_near_spec(reg_path):
    from open_guji_cv.groups import near_registry as NR
    reg = NR.load(reg_path)
    assert reg.glyph_near_spec("guan") == {"chars": ["官", "宫", "宮"], "fold": {"宮": "宫"}, "methods": {}}
    assert reg.glyph_near_spec("guan", book="bk") == {"chars": ["官", "宫", "宮"], "fold": {"宮": "宫"},
                                                      "methods": {"cnn_small": "m/g"}, "delta": 0.05}
    assert reg.glyph_near_spec("wm", trigger="member") == {"chars": ["未", "末"], "methods": {}, "trigger": "member"}
    with pytest.raises(ValueError):
        reg.glyph_near_spec("wm", colour="red")


def test_expand_refs_without_ref_is_identity_and_hash_unchanged(reg_path):
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.groups import near_registry as NR
    from open_guji_cv.steps.glyph_near import GlyphNearParams
    plain = {"gong": {"chars": ["宫", "宮", "官"], "fold": {"宮": "宫"}, "trigger": "close", "delta": 0.03}}
    assert NR.expand_refs(plain, path=reg_path) is plain
    assert NR.expand_refs({}, path=reg_path) == {}
    assert params_hash(GlyphNearParams(groups=NR.expand_refs(plain, path=reg_path))) == params_hash(GlyphNearParams(groups=plain))


def test_expand_refs_feeds_3b_trigger(reg_path):
    from open_guji_cv.groups import near_registry as NR
    from open_guji_cv.steps.glyph_near import trigger_group
    got = NR.expand_refs({"gong": {"ref": "guan", "trigger": "member"}, "x": {"chars": ["天", "夭"]}}, book="bk",
                         path=reg_path)
    assert got["gong"] == {"chars": ["官", "宫", "宮"], "fold": {"宮": "宫"}, "methods": {"cnn_small": "m/g"},
                           "delta": 0.05, "trigger": "member"}
    assert got["x"] == {"chars": ["天", "夭"]}
    assert trigger_group([("宮", 0.9)], "宮", {"gong": got["gong"]}) == ("gong", "member")


# ── 守卫：提交的表与生成脚本一致 ─────────────────────────────────────


def test_committed_v2_matches_generator():
    committed = REPO / "config" / "near_groups" / "v2.json"
    assert committed.read_text(encoding="utf-8") == B.dumps(B.build_from_repo()), (
        "config/near_groups/v2.json 与来源（注册字组表、confusable、near_groups.json…）不同步："
        "跑 python scripts/build_near_groups_v2.py 再提交")


def test_committed_v2_loads_and_covers_registry():
    from open_guji_cv.groups import near_registry as NR
    from open_guji_cv.groups.registry import FLOW_GROUPS
    reg = NR.load()
    assert set(FLOW_GROUPS) <= set(reg.groups)
    assert reg.meta["books"] == []                       # 仓里的版本不带书级输入
    for gid, g in FLOW_GROUPS.items():
        assert set(reg.get(gid).chars) == set(g.members)
