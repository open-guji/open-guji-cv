# -*- coding: utf-8 -*-
"""`report/run.py::_grade_by_witness`：多证人对勘接上 `collation_grade` 分层。

只测分层本身怎么接（按证人分开统计、写回 `Diff.grade`、汇总数字对不对），
不测 `collate_page`/`diff_page` 怎么算差异——那是 `report/collate.py` 的事，
已有别的测试钉住对齐口径。这里直接手造 `Diff` 与 `pages_out`，不碰 ProductStore。
"""
from __future__ import annotations

from open_guji_cv.report.collate import Diff
from open_guji_cv.report.run import _grade_by_witness
from open_guji_cv.report.witness import Witness


def _diff(witness, kind, char, ref, *, page=1, human=False, **kw) -> Diff:
    return Diff(id=f"tbook:{page}:1:1", page=page, col=1, slot=1, sub=None, kind=kind,
               char=char, ref=ref, witness=witness, human=human, **kw)


def _witness(label="证人甲") -> Witness:
    return Witness(name=label, label=label, quality="best", text="")


def _page_stat(page, n_slots=10, excluded=0, equal=9):
    return {"page": page, "witnesses": {"证人甲": {"n_slots": n_slots, "n_excluded": excluded,
                                                "n_equal": equal}}}


def test_grade_written_back_onto_each_diff():
    """避諱字对（1 次也算）分层结果要写回 `Diff.grade`，不是留在旁边的副本上。"""
    w = _witness()
    diffs = [_diff(w.label, "sub.other", "金", "虜")]
    pages_out = [_page_stat(1)]
    _grade_by_witness(diffs, pages_out, {w.label: []}, [w])
    assert diffs[0].grade == "taboo"


def test_repeat_counted_per_witness_not_pooled():
    """两个证人各自统计重复度——甲那边够 3 次是系统性，乙那边只 1 次该留在存疑，
    即便把两边的条目摆在一起看总次数够了。分层要是被合并统计，这条会把乙的
    那条也判成 systematic，测试就抓不出来。"""
    a, b = _witness("证人甲"), _witness("证人乙")
    diffs = ([_diff(a.label, "sub.other", "畱", "留", page=p) for p in range(3)]
            + [_diff(b.label, "sub.other", "畱", "留", page=1)])
    pages_out = [{"page": p, "witnesses": {
        a.label: {"n_slots": 10, "n_excluded": 0, "n_equal": 9},
        b.label: {"n_slots": 10, "n_excluded": 0, "n_equal": 9}}} for p in range(3)]
    _grade_by_witness(diffs, pages_out, {a.label: [], b.label: []}, [a, b])
    assert [d.grade for d in diffs if d.witness == a.label] == ["systematic"] * 3
    assert [d.grade for d in diffs if d.witness == b.label] == ["suspect"]


def test_summary_counts_settled_and_todo():
    w = _witness()
    diffs = [_diff(w.label, "sub.other", "金", "虜"),      # taboo → settled
            _diff(w.label, "sub.other", "甲", "乙")]        # 无已知关系 → suspect/todo
    pages_out = [_page_stat(1)]
    out = _grade_by_witness(diffs, pages_out, {w.label: []}, [w])
    assert out[w.label]["n_settled"] == 1
    assert out[w.label]["n_todo"] == 1
    assert out[w.label]["grade_counts"]["taboo"] == 1
    assert out[w.label]["grade_counts"]["suspect"] == 1


def test_misanchored_pages_excludes_unanchored_pages():
    """整段错位（不一致率高但锚上了）和整页锚定失败是两件事——锚定失败的页
    压根不出 diff，`misanchored_pages` 不该把它也算进「整段错位」。"""
    w = _witness()
    # p2：锚上了但几乎全错（不一致率高）；p3：锚定失败（unanchored），没有 diff
    diffs = [_diff(w.label, "sub.other", "甲", "乙", page=2)]
    pages_out = [
        {"page": 2, "witnesses": {w.label: {"n_slots": 10, "n_excluded": 0, "n_equal": 1}}},
        {"page": 3, "witnesses": {w.label: {"n_slots": 10, "n_excluded": 0, "n_equal": 0}}},
    ]
    out = _grade_by_witness(diffs, pages_out, {w.label: [3]}, [w])
    assert out[w.label]["misanchored_pages"] == [2]
