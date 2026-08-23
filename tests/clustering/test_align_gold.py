"""逐实例金标落标规则的单测（align_gold）。

重点测「哪些位置**不**该落标」——采信规则的价值全在排除项上。
"""

import pytest

from open_guji_cv.clustering.align_eval import build_ngram_index
from open_guji_cv.clustering.align_gold import _accept_opcodes, gold_for_page


class FakeInst:
    def __init__(self, i):
        self.id = f"b:1:1:{i}"
        self.col = 1
        self.idx = i
        self.patch_path = f"patches/1/1_{i}.png"


def _insts(n):
    return [FakeInst(i + 1) for i in range(n)]


def test_equal_block_accepted():
    ops = [("equal", 0, 5, 0, 5)]
    assert _accept_opcodes(ops) == [("equal", 0, 5, 0, 5)]


def test_short_replace_between_flanks_accepted():
    ops = [("equal", 0, 3, 0, 3), ("replace", 3, 5, 3, 5),
           ("equal", 5, 9, 5, 9)]
    tags = [t for t, *_ in _accept_opcodes(ops)]
    assert tags == ["equal", "replace", "equal"]


def test_long_replace_rejected():
    """长替换段内部可能同时藏着漏切与多切，长度凑巧相抵，逐位对应仍是错的。"""
    ops = [("equal", 0, 3, 0, 3), ("replace", 3, 12, 3, 12),
           ("equal", 12, 15, 12, 15)]
    tags = [t for t, *_ in _accept_opcodes(ops)]
    assert "replace" not in tags


def test_unflanked_replace_rejected():
    ops = [("replace", 0, 2, 0, 2), ("equal", 2, 6, 2, 6)]
    tags = [t for t, *_ in _accept_opcodes(ops)]
    assert "replace" not in tags


def test_unequal_replace_rejected():
    """两侧不等长 = 切分多切/漏切，位置对应已断。"""
    ops = [("equal", 0, 3, 0, 3), ("replace", 3, 5, 3, 8),
           ("equal", 5, 9, 8, 12)]
    tags = [t for t, *_ in _accept_opcodes(ops)]
    assert "replace" not in tags


def test_insert_and_delete_rejected():
    ops = [("equal", 0, 3, 0, 3), ("insert", 3, 3, 3, 5),
           ("delete", 3, 5, 5, 5), ("equal", 5, 9, 5, 9)]
    tags = [t for t, *_ in _accept_opcodes(ops)]
    assert tags == ["equal", "equal"]


def test_gold_values_come_from_reference_not_transcription():
    """金标取参考语料的字；转写错的位置照样进集，且金标是**正确**的那个。"""
    corpus = "欽定四庫全書總目提要卷首一聖諭恭錄在前"
    text = "欽定四庫全書總目提要卷首二聖諭恭錄在前"   # 下标 12（一→二）
    insts = _insts(len(text))
    pg = gold_for_page("1", insts, text, corpus, build_ngram_index(corpus))
    assert pg.anchored
    by_pos = {i.pos: i for i in pg.items}
    assert by_pos[12].gold == "一"
    assert by_pos[12].transcribed == "二"
    assert by_pos[12].opcode == "replace"


def test_unanchorable_page_yields_no_gold():
    corpus = "欽定四庫全書總目提要卷首一聖諭恭錄在前"
    text = "毫不相干的另一段文字內容與語料無關聯"
    insts = _insts(len(text))
    pg = gold_for_page("1", insts, text, corpus, build_ngram_index(corpus))
    assert not pg.anchored
    assert pg.items == []
    assert pg.n_uncertain == len(insts)
