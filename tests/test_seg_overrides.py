"""feedback/seg_overrides.py：按需读、列级视图、「屏蔽格位表」规则（doc/切分覆盖.md 第三节）。"""
from __future__ import annotations

from open_guji_cv.feedback import lookup
from open_guji_cv.feedback import seg_overrides as so


def _fake(monkeypatch, calls: list[str], **tables):
    def mk(name):
        def f(book, *a, **k):
            calls.append(name)
            return tables.get(name, {})
        return f
    for name in ("resolved_manual_cells", "resolved_cuts", "resolved_slots", "resolved_solo_notes",
                 "resolved_forced_jiazhu", "resolved_forced_main", "resolved_head_raise", "resolved_pins"):
        monkeypatch.setattr(lookup, name, mk(name))


def test_lazy_page_manual_reads_only_manual_cells(monkeypatch):
    calls: list[str] = []
    _fake(monkeypatch, calls, resolved_manual_cells={(3, 2): [{"slot": 1}], (4, 1): [{"slot": 1}]})
    ov = so.SegOverrides("b")
    assert ov.page_manual(3) == {2: [{"slot": 1}]}
    assert calls == ["resolved_manual_cells"]          # 职名页分支只问钉子，不读切线和事件
    ov.page_manual(4)
    assert calls == ["resolved_manual_cells"]          # 每张表只读一次


def test_empty_column(monkeypatch):
    _fake(monkeypatch, [])
    c = so.SegOverrides("b").column(1, 1)
    assert c.empty and not c.blocks_layout


def test_blocks_layout_each_kind(monkeypatch):
    cases = {
        "resolved_slots": {(1, 2): lookup.ResolvedColumn(22, False)},
        "resolved_cuts": {(1, 2, 5): "straight"},
        "resolved_pins": {(1, 2, 5): 400.0},
        "resolved_solo_notes": {(1, 2): {7}},
        "resolved_forced_jiazhu": {(1, 2): {7}},
        "resolved_forced_main": {(1, 2): {7}},
    }
    for name, table in cases.items():
        _fake(monkeypatch, [], **{name: table})
        ov = so.SegOverrides("b")
        assert ov.column(1, 2).blocks_layout, name
        assert not ov.column(1, 3).blocks_layout, name    # 别的列不受牵连
        assert not ov.column(2, 2).blocks_layout, name    # 别的页不受牵连


def test_head_raise_and_manual_do_not_block_layout(monkeypatch):
    # 抬头裁决让表按它挪格号（_reraise），不屏蔽表；整列钉子在切完后整列替换，也不在这条规则里
    _fake(monkeypatch, [], resolved_head_raise={(1, 2): 1}, resolved_manual_cells={(1, 2): [{"slot": 1}]})
    c = so.SegOverrides("b").column(1, 2)
    assert c.head_raise == 1 and c.manual_cells == [{"slot": 1}]
    assert not c.blocks_layout and not c.empty


def test_column_view_filters_cuts_and_pins(monkeypatch):
    _fake(monkeypatch, [], resolved_cuts={(1, 2, 5): "a", (1, 3, 6): "b"}, resolved_pins={(1, 2, 8): 10.0, (2, 2, 8): 11.0})
    c = so.SegOverrides("b").column(1, 2)
    assert c.cuts == {5: "a"} and c.pins == {8: 10.0}
