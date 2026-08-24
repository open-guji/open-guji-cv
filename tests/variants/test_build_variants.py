"""build_variants.py 解析/合并函数单测：内嵌小样本，不碰网络。"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "build_variants", REPO / "scripts" / "build_variants.py")
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)


# ── Unihan ──────────────────────────────────────────────

UNIHAN_SAMPLE = """\
# comment line
U+3405\tkSemanticVariant\tU+4E94<kMatthews
U+84CB\tkSemanticVariant\tU+8462 U+76D6
U+340A\tkSpoofingVariant\tU+340B
U+4E00\tkTraditionalVariant\tU+4E00
U+4E01\tkDefinition\tnot a variant prop
"""


def test_parse_unihan_strips_angle_annotation():
    edges, _ = bv.parse_unihan_variants(UNIHAN_SAMPLE)
    assert ("㐅", "五", "unihan:kSemanticVariant") in edges


def test_parse_unihan_multiple_values_and_tags():
    edges, stats = bv.parse_unihan_variants(UNIHAN_SAMPLE)
    assert ("蓋", "葢", "unihan:kSemanticVariant") in edges
    assert ("蓋", "盖", "unihan:kSemanticVariant") in edges
    assert ("㐊", "㐋", "unihan:kSpoofingVariant") in edges
    assert stats["edges"] == 4


def test_parse_unihan_skips_self_loop_and_foreign_props():
    edges, stats = bv.parse_unihan_variants(UNIHAN_SAMPLE)
    assert stats["self_loop"] == 1          # U+4E00 → 自身
    assert stats["prop_ignored"] == 1       # kDefinition
    assert all(t.startswith("unihan:") for _, _, t in edges)


# ── cjkvi ───────────────────────────────────────────────

CJKVI_SAMPLE = """\
# 注释
twedu/variant,<rev>,twedu/regular
twedu/variant,<name>,異體字（民國教育部）
略,twedu/variant,畧
充,twedu/variant,𠑽,[充=⿱亠厶]
倔,twedu/variant,⿰革𡲬
虜[田],twedu/variant,虜[毌]
韌,twedu/variant,韌[刄]
夫,twedu/variant,伕→夫
一,twedu/variant,一
短行
"""


def test_parse_cjkvi_basic_and_extra_column():
    edges, _ = bv.parse_cjkvi_variants(CJKVI_SAMPLE, "twedu")
    assert ("略", "畧", "twedu") in edges
    assert ("充", "𠑽", "twedu") in edges   # 第四列注记被忽略


def test_parse_cjkvi_skips_dirty_lines():
    edges, stats = bv.parse_cjkvi_variants(CJKVI_SAMPLE, "twedu")
    assert stats["edges"] == 2
    assert stats["line_meta"] == 2      # twedu/... 元数据行
    assert stats["col1_bad"] == 1       # 虜[田]
    assert stats["col3_bad"] == 3       # IDS / 韌[刄] / 伕→夫
    assert stats["self_loop"] == 1
    assert stats["line_short"] == 1
    chars = {c for a, b, _ in edges for c in (a, b)}
    assert all(len(c) == 1 for c in chars)


# ── yitizi ──────────────────────────────────────────────

YITIZI_JS = """\
const Yitizi = {
  yitiziData: {
"蓋":"盖葢",
"略":"畧"
},
  get: function get(c) { return []; }
};
"""


def test_parse_yitizi_js():
    edges, stats = bv.parse_yitizi_js(YITIZI_JS)
    assert ("蓋", "盖", "yitizi") in edges
    assert ("蓋", "葢", "yitizi") in edges
    assert ("略", "畧", "yitizi") in edges
    assert stats["entries"] == 2
    assert stats["edges"] == 3


def test_parse_yitizi_js_rejects_changed_format():
    import pytest
    with pytest.raises(ValueError):
        bv.parse_yitizi_js("module.exports = {};")


# ── 合并 ─────────────────────────────────────────────────

def test_merge_edges_direction_independent_with_tag_union():
    pairs = bv.merge_edges([
        [("葢", "蓋", "twedu")],                    # 反向录入
        [("蓋", "葢", "unihan:kSemanticVariant"),
         ("蓋", "盖", "yitizi")],
    ])
    # 只存 ord 小的一侧：蓋(U+84CB) < 葢(U+8462)? 不：8462 < 84CB
    assert pairs["葢"]["蓋"] == ["twedu", "unihan:kSemanticVariant"]
    assert pairs["盖"]["蓋"] == ["yitizi"]


def test_merge_edges_deterministic_under_input_order():
    e1 = [("甲", "乙", "twedu"), ("乙", "丙", "hydzd"), ("甲", "乙", "yitizi")]
    e2 = list(reversed(e1))
    j1 = json.dumps(bv.merge_edges([e1]), sort_keys=True, ensure_ascii=False)
    j2 = json.dumps(bv.merge_edges([e2]), sort_keys=True, ensure_ascii=False)
    assert j1 == j2


def test_is_cjk_char():
    assert bv.is_cjk_char("蓋")
    assert bv.is_cjk_char("𠑽")             # 扩展 B
    assert not bv.is_cjk_char("")
    assert not bv.is_cjk_char("ab")
    assert not bv.is_cjk_char("⿰")          # IDS 算符不是汉字
    assert not bv.is_cjk_char("虜[田]")
