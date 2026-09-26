# -*- coding: utf-8 -*-
"""Step9 结果整理 · 坐标转字符位：字位流 → guji-markdown 记号。

2026-09-20 重写。原先是把隔壁 `open-guji-dataset` 的 `guji-markdown-render`
分片逐条读进来比对固化文本，外加一条「那个分片里必须有这 5 个 id」。
分片不在就整条 skip（云端从没跑过），而「分片里有哪几条」本来就该由测试集仓
自己守——一个仓的测试去管另一个仓的数据长什么样，是这轮要根治的那类依赖。

真实页的固化快照留在测试集仓（那是它该在的地方）。这里改为**每种记号各造
一条最小用例**，钉住这一层映射本身：

| 记号 | 意思 | 用例 |
|---|---|---|
| `^` | 抬头级数（`ColumnCells.n_raised`）| `test_raised_prefix` |
| `.` | 行首空格（挪抬）| `test_lead_blank_prefix` |
| `<a\\|b>` | 雙行夹注，a 全部在前、b 全部在后 | `test_jiazhu_pairs` |
| `<注>` | 單行小注（不带 `\\|`）| `test_solo_note` |
| `[[]]` | 阙文（认不出的字）| `test_unreadable_is_a_gap` |
| （跳过）| 排除名单里的**非字**（墨污/切坏）| `test_not_a_char_is_skipped` |
| `[[]]` | 排除名单里的**切坏/残损**——字确实在，只是图块不能进库 | `test_seg_defect_still_occupies_a_slot` |

最后两条是 `report/slots.py` 里那条按**理由**分两路的判据，2026-09-20 才从
bxgb 对勘里查出来（131 条 seg_defect 曾被当非字整片吃掉，对勘报成 129 条
「整理本有刻本无」）。它俩必须成对出现在这儿——只留一条的话，判据退回
「一律跳过」时测试照样绿。
"""

from __future__ import annotations

from open_guji_cv.products.kinds.cells import CellRec
from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.render.guji_markdown import render_column
from open_guji_cv.report.slots import _to_slot
from open_guji_cv.utils.jiazhu_order import sort_by_reading

BOOK, PAGE, COL = "tbook", 1, 1


def _cell(slot: int, kind: str = "char", sub: str | None = None) -> CellRec:
    return CellRec(slot=slot, pos=0, y0=0, y1=0, x0=0, x1=0, kind=kind, sub=sub,
                   order=0)


def _rec(slot: int, char: str | None = None, *, admit: bool = True,
         sub: str | None = None, doubts=None, evidence=None) -> AdmitRec:
    return AdmitRec(id=f"{BOOK}:{PAGE}:{COL}:{slot}", slot=slot, sub=sub,
                    admit=admit, char=char, doubts=doubts or [],
                    evidence=evidence or {})


def _render(cells: dict, recs: list[AdmitRec], *, n_raised: int = 0,
            n_lead_blank: int = 0) -> str:
    """照 `report.slots.page_slots()` 的同一条路把快照转成字位流再渲染。"""
    slots = [_to_slot(BOOK, PAGE, COL, r, cells.get((r.slot, r.sub or "")))
             for r in sort_by_reading(recs)]
    return render_column(slots, n_raised, n_lead_blank)


def _plain(chars: str, start: int = 1):
    """一列普通正文：`{(slot, ""): CellRec}` 与对应的 AdmitRec。"""
    cells = {(start + i, ""): _cell(start + i) for i in range(len(chars))}
    recs = [_rec(start + i, ch) for i, ch in enumerate(chars)]
    return cells, recs


def test_plain_column_is_just_the_characters():
    cells, recs = _plain("臣等謹按")
    assert _render(cells, recs) == "臣等謹按"


def test_raised_prefix():
    """抬头级数 → 行首 `^`。级数读 Step3 的 `n_raised`（离散可靠，3419 列零例外）。"""
    cells, recs = _plain("諭旨")
    assert _render(cells, recs, n_raised=1) == "^諭旨"
    assert _render(cells, recs, n_raised=2) == "^^諭旨"


def test_lead_blank_prefix():
    """行首空白格 → `.`。**记的是版面事实（字前空出 n 格），不判定敬语**
    （用户 2026-09-11 裁，见 guji_markdown 模块头边界 2）。"""
    cells, recs = _plain("臣等", start=3)
    cells[(1, "")] = _cell(1, "blank")
    cells[(2, "")] = _cell(2, "blank")
    assert _render(cells, recs, n_lead_blank=2) == "..臣等"


def test_jiazhu_pairs():
    """雙行夹注：同一段里 a 半格全部在前、b 半格全部在后，拼成 `<a…|b…>`。"""
    cells = {(1, ""): _cell(1)}
    recs = [_rec(1, "按")]
    for slot, a, b in ((2, "浙", "江"), (3, "採", "進")):
        cells[(slot, "a")] = _cell(slot, "jiazhu_a", "a")
        cells[(slot, "b")] = _cell(slot, "jiazhu_b", "b")
        recs += [_rec(slot, a, sub="a"), _rec(slot, b, sub="b")]
    assert _render(cells, recs) == "按<浙採|江進>"


def test_solo_note():
    """單行小注写指令式 `:jz[注]{type=单行}`（spec/directives.md 的 jz type）——
    不带 `|` 的 `<注>` 与只剩一半的雙行夹注分不开，维基文库导出要区分二者。"""
    cells = {(1, ""): _cell(1)}
    recs = [_rec(1, "按")]
    for slot, ch in ((2, "瀛"), (3, "楫")):
        cells[(slot, "")] = _cell(slot, "jiazhu_solo")
        recs.append(_rec(slot, ch))
    assert _render(cells, recs) == "按:jz[瀛楫]{type=单行}"


def test_unreadable_is_a_gap():
    """认不出的字（`admit=False` 且 `char is None`）→ 阙文 `[[]]`，占一格。"""
    cells, recs = _plain("臣等")
    cells[(3, "")] = _cell(3)
    recs.append(_rec(3, None, admit=False))
    assert _render(cells, recs) == "臣等[[]]"


def test_not_a_char_is_skipped():
    """排除名单里的**非字**（墨污、切坏到不成字）→ 这一格本不存在，跳过不占位。

    2026-09-11 用户核实 vol02 p1-20 时发现最初版本把它们也标成 `[[]]`：
    20 处里 19 处其实是 excluded。
    """
    cells, recs = _plain("臣等")
    cells[(3, "")] = _cell(3)
    recs.append(_rec(3, None, admit=False, doubts=["excluded"],
                     evidence={"excluded": "human:not_a_char"}))
    assert _render(cells, recs) == "臣等"


def test_seg_defect_still_occupies_a_slot():
    """排除名单里的**切坏 / 原刻残损** → 字确实在这儿，只是图块不能进库：
    字位必须占住，文本层出阙文。

    2026-09-20 bxgb 对勘查出来的：155 条名单里 131 条是 seg_defect
    （「舉手一揖」的 手、「十一月」的 月、「縉雲」的 縉），此前一律按非字
    跳过，对勘因此报成 129 条「整理本有刻本无」，80 条正落在这些格上。
    """
    for reason in ("seg_defect", "damaged"):
        cells, recs = _plain("臣等")
        cells[(3, "")] = _cell(3)
        recs.append(_rec(3, None, admit=False, doubts=["excluded"],
                         evidence={"excluded": f"human:{reason}"}))
        assert _render(cells, recs) == "臣等[[]]", f"{reason} 的字位被吃掉了"


def test_missing_cell_falls_back_to_a_plain_char():
    """Step3 里查不到这一格时按正文字处理，不猜它是夹注或 blank。

    猜错会让读序和夹注配对一起错，比少一格的后果大（`_to_slot` 的注释）。
    """
    cells, recs = _plain("臣等")
    recs.append(_rec(3, "謹"))          # cells 里故意没有 slot 3
    assert _render(cells, recs) == "臣等謹"
