"""M7 块 A：字组 IDS 展开（`groups/ids.py`）。只读仓里的 config，不依赖 dataset。"""
from pathlib import Path

from open_guji_cv.groups.ids import expand, group_structures, parse, slot_options

GROUP_DIR = Path(__file__).resolve().parents[1] / "config" / "groups" / "yi_560"
YI = "彝彞彜彛𢑴𢑱"


def test_parse_roundtrip():
    assert str(parse("⿳彑⿰米糸廾")) == "⿳彑⿰米糸廾"


def test_yi_six_fully_expanded_same_shape():
    st = group_structures(YI, GROUP_DIR)
    assert st["彝"] == ["⿳彑⿰米糸廾"]          # 用户给的完全展开样例
    assert st["彜"] == ["⿳彑⿰米分廾"]          # 原表 ⿱彑𪪷，必须展开到 米分
    # 六字的所有写法顶层都是 ⿳，且中段都是 ⿰米X
    for ch, seqs in st.items():
        assert seqs, ch
        for s in seqs:
            n = parse(s)
            assert n.idc == "⿳" and n.kids[1].idc == "⿰" and n.kids[1].kids[0].ch == "米", (ch, s)


def test_slot_options_match_user_three_part_reading():
    cols = slot_options(group_structures(YI, GROUP_DIR), "⿳")
    assert cols[0] == {"彑", "彐"}
    assert cols[1] == {"⿰米糸", "⿰米分"}
    assert cols[2] == {"廾", "大"}


def test_atomic_char_returns_itself():
    assert [str(n) for n in expand("人", set())] == ["人"]


def test_resolver_identify_ids_then_char():
    from open_guji_cv.groups.ids import IdsResolver
    r = IdsResolver(YI, GROUP_DIR)
    assert r.canonical["𢑱"] == "⿳彑⿰米分大"                      # 用户 10-17：最准确 IDS
    assert r.resolve("⿳彑⿰米分大").kind == "exact"
    x = r.resolve("⿳彐⿰米分大")                                    # 字形可能写成 彐，仍精确归 𢑱
    assert (x.char, x.kind, x.flag) == ("𢑱", "form", None)
    n = r.resolve("⿳彑⿰米糸大")                                    # 无对应字符 → 最近异体 + 旗
    assert (n.char, n.kind, n.flag) == ("𢑴", "nearest", "nearest_variant")
    assert r.resolve("⿳彑⿰米糸日").char is None                    # 不认识就弃权
