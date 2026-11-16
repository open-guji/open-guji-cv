"""5b 候选按异体族展开（clustering/rare_family）与升级档取全部扩展区（charset_spec 的 unicode-all）。"""
from __future__ import annotations

from open_guji_cv.clustering import rare_family as RF
from open_guji_cv.clustering.charset_spec import build_charsets

FAM = {"內": ["内", "𠘨", "㐻"], "步": ["歩"], "候": ["𠉀", "𠋫"]}


def _fam(c):
    return FAM.get(c, [])


def test_expand_only_top_m_and_skips_present():
    got = RF.expand_family(["內", "步", "肉"], top_m=1, family_of=_fam)
    assert got == [("内", "內"), ("㐻", "內"), ("𠘨", "內")]          # 基本区在前，扩展区在后
    got = RF.expand_family(["內", "内", "步"], top_m=3, family_of=_fam)
    assert got == [("㐻", "內"), ("𠘨", "內"), ("歩", "步")]          # 已在候选里的不重复


def test_expand_cap_and_keep():
    assert len(RF.expand_family(["內", "步", "候"], top_m=3, cap=2, family_of=_fam)) == 2
    got = RF.expand_family(["內"], keep=lambda c: c != "内", family_of=_fam)
    assert [c for c, _ in got] == ["㐻", "𠘨"]
    assert RF.expand_family([], family_of=_fam) == []
    assert RF.expand_family(["內"], top_m=0, family_of=_fam) == []


def test_family_hit_both_directions():
    assert RF.family_hit(["內", "肉"], "内", family_of=_fam)         # 首位的族里有金标
    assert RF.family_hit(["歩"], "步", family_of=_fam)               # 金标的族里有首位
    assert RF.family_hit(["內"], "內", family_of=_fam)
    assert not RF.family_hit(["肉", "內"], "内", family_of=_fam)     # 只看首位
    assert not RF.family_hit([], "内", family_of=_fam)


def test_expand_with_real_relation_db():
    got = [c for c, _ in RF.expand_family(["內"], cap=50)]
    assert "内" in got


def test_escalate_unicode_all_reaches_ext_c_and_later():
    """`font.charset.escalate: unicode-all`：升级档是基集之外的全部已编码汉字（扩 B 到扩 J）。"""
    base, esc_b = build_charsets("unicode-cjk-a", "unicode-ext-b", None, False, False)
    base2, esc_all = build_charsets("unicode-cjk-a", "unicode-all", None, False, False)
    assert base == base2
    assert set(esc_b) <= set(esc_all)
    assert not set(base) & set(esc_all)
    for ch in "𮪍𫾣𭔃𮅕":                                            # 扩 C 以后，殿本类外字的金标
        assert ch in esc_all and ch not in esc_b
    assert len(esc_all) > 60_000                                     # 扩 G 以后（U+30000 起）被 `_cjk` 挡在外面，见 eval_rare_escalate 模块头
