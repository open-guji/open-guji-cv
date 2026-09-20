# -*- coding: utf-8 -*-
"""v2 产物 → v1 CharInstance 的桥（阶段 B0）。

守住两条口径：格号换算（v1 idx 从 0 且连续 / v2 slot 从 1、抬头负数、
夹注 a/b 共用）与 bbox 空间（优先规范空间 bbox_page）。

2026-09-20 重写：原先四条都读工作区里 `vol01/24` 那份 `cell_shrink` 产物，
产物不在就 skip——于是最要紧的那条（**抬头列 slot 是负数，idx 不许跟着变负**）
只在「这次跑批恰好有抬头列」时才真的执行到。现在合成一页带抬头列的版式
（左起第一列顶上多写一个字，Step2 的闸会给它 `n_raised_hint=1`，Step3 于是
切出 slot=-1 的抬头格），跑真的 Step2→Step4 链路，靶子每次都在。
"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import run_keben_chain
from open_guji_cv.core.book import load_book
from open_guji_cv.steps._v1_bridge import export_v1_view, to_char_instances

#: 用 fixture 册「keben」（八列二十一字）而不是内存造的册——`export_v1_view`
#: 内部会 `load_book(book)` 拿 `dev_set` 当默认页集，需要一份真的册 yaml。
BOOK, PAGE, PERIOD = "keben", 1, 60


def _chain(tmp_path, monkeypatch, *, raised: bool = False):
    """合成一页与 fixture 册同版式的页，跑到 Step4。

    `raised=True` 时左起第一列（= 末列）顶上多写一个字：闸2 按墨跨度给它
    `n_raised_hint=1`，Step3 于是切出 slot=-1 的抬头格——这正是下面那条
    「idx 不许跟着 slot 变负」要打的靶子。
    """
    bk = load_book(BOOK)
    kw: dict = dict(n_cols=bk.expected_cols, period=PERIOD, n_chars=bk.chars_per_line)
    if raised:
        kw.update(top_gap=PERIOD, col_top_gap={1: 0},
                  col_n_chars={1: bk.chars_per_line + 1})
    return run_keben_chain(tmp_path, monkeypatch, book=bk, **kw)


def test_bridge_emits_v1_shaped_instances(tmp_path, monkeypatch, ws):
    ctx, _ = _chain(tmp_path, monkeypatch)
    insts = to_char_instances(BOOK, PAGE, ctx.store)
    assert insts, "合成页跑完 Step4 却一个实例都没有"
    i = insts[0]
    # v1 的字段都在
    for f in ("id", "book", "page", "col", "idx", "bbox", "cell_type",
              "patch_path", "ink_ratio", "flags", "sub"):
        assert hasattr(i, f), f"缺字段 {f}"
    assert i.book == BOOK and i.page == str(PAGE)
    assert len(i.bbox) == 4


def test_idx_is_physical_position_not_slot(tmp_path, monkeypatch, ws):
    """v1 的 idx 必须是**物理位置**（0 起、单调），不是 v2 的 slot。

    slot 在抬头列是负数、夹注 a/b 共用同一个值，直接拿它当 idx 会让下游按
    `page:col:idx` 建的索引撞车。
    **不查连续性**：Step4 只发 cell_type=char 的格，空白格不在这里——列首低
    格起排（vol01/137、141 从 idx=2 起）和列中段整段留白（vol01/26c5 空 7~20）
    都是真实版面，不是格号换算错。
    """
    ctx, out = _chain(tmp_path, monkeypatch, raised=True)

    # 先确认靶子在：这一页确实切出了负 slot（抬头格）
    negative = {c.col for c in out["cells"].columns
                for cell in c.cells if cell.slot <= 0}
    assert negative, "合成的抬头列没切出负 slot，这条用例就测不到它要测的东西"

    insts = to_char_instances(BOOK, PAGE, ctx.store)
    by_col: dict[int, list] = {}
    for i in insts:
        by_col.setdefault(i.col, []).append(i)
    assert by_col

    for col, recs in by_col.items():
        idxs = [r.idx for r in recs]
        assert min(idxs) >= 0, f"c{col} 出现负 idx：{min(idxs)}"
        # 重复只允许来自夹注 a/b（同一物理位置的两个半格）
        for x in sorted(set(idxs)):
            if idxs.count(x) == 1:
                continue
            subs = {r.sub for r in recs if r.idx == x}
            assert subs <= {"a", "b"} and len(subs) > 1, \
                f"c{col} idx={x} 重复 {idxs.count(x)} 次但不是夹注：{subs}"
        if col in negative:
            assert min(idxs) == 0, \
                f"c{col} 有抬头格（slot 负）但 idx 没落在 0：{sorted(set(idxs))[:3]}"


def test_bbox_prefers_the_canonical_page_space(tmp_path, monkeypatch, ws):
    """bbox 要用 bbox_page（规范空间），退回列图坐标时必须打标记。"""
    ctx, _ = _chain(tmp_path, monkeypatch)
    insts = to_char_instances(BOOK, PAGE, ctx.store)
    assert insts
    fell_back = [i for i in insts if "bbox_is_column" in i.flags]
    assert not fell_back, (
        "v2 链正常跑出来的都该有 bbox_page；退回列图坐标的有 "
        f"{len(fell_back)} 个：{[i.id for i in fell_back[:3]]}")


def test_export_view_is_loadable_by_v1_loader(tmp_path, monkeypatch, ws):
    """导出的目录要能被 v1 的 load_index 原样读回——这是桥存在的意义。"""
    from open_guji_cv.clustering.extractor import load_index

    _chain(tmp_path, monkeypatch)
    v = export_v1_view(BOOK, pages=[PAGE], root=tmp_path / "view")
    assert v.index_path.exists(), "导出没落 index.jsonl"
    insts = load_index(v.root)
    assert insts, "导出的 index.jsonl 读不出实例"
    with_patch = [i for i in insts if (v.root / i.patch_path).exists()]
    chars = [i for i in insts if i.cell_type == "char"]
    assert chars
    assert len(with_patch) >= len(chars) * 0.9, \
        f"只有 {len(with_patch)}/{len(chars)} 个 char 实例落了图块"
