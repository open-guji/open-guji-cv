"""版框带内缘钉桩的字墨闸回归。

## 这个 bug 长什么样

钉桩把图块条带的上界钉在版框带内缘，防止框墨进条带。原先只有一条**比例闸**
（最多吃掉 0.35 × 格高），它只问「吃掉几分之几」，不问「吃掉的是不是字」。

实测 vol01 十个页面的首个正文格：桩落在 y=143~150，而字墨从 y≈123 就开始，
差 32~39px 恰好卡在 40px 限额之下 → 每次都钉，每次都把「非」「簡」这类字的
顶横整条切掉。用户在 10 个不同页面反复标 slot 2 截断，33 条切分缺陷里
**17 条压在这一格**。

修法是补一条**直接看墨**的闸：桩要跨过的那段里若已有成段字墨就不钉。
本模块的红线本来就是「宁可留框渣，绝不吞字」。

## 为什么它躲过了 R4 尺子

R4 只量「紧贴紧框的墨」，而这里被切掉的墨与紧框之间隔着空白（顶横与字身
之间本就有距离），量法够不着。修复后 R4 从 0.51% 降到 0.05% —— 说明它
**部分**能测到，但远不是全部。缺陷聚集（人裁标注按格位聚）才是发现它的手段。
"""

from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.clustering.extractor import (FRAME_BAND_MAX_CUT,
                                               PIN_INK_ROW_T, PIN_INK_RUN,
                                               _has_char_ink)


def _page(rows: list[tuple[int, int, float]], w: int = 180, h: int = 260):
    """按 (起, 止, 墨率) 造一张灰度图。"""
    img = np.full((h, w), 255, np.uint8)
    for a, b, r in rows:
        n = int(w * r)
        img[a:b, :n] = 0
    return img


def test_char_ink_detected():
    """成段字墨（连续多行、墨率够）必须认出来——认不出就会被钉桩切掉。"""
    img = _page([(20, 40, 0.30)])
    assert _has_char_ink(img, 0, 180, 10, 50)


def test_thin_frame_residue_not_char_ink():
    """框渣是薄的、断续的——不能当成字墨，否则桩永远不钉、框墨全进来。"""
    img = _page([(20, 22, 0.30), (30, 31, 0.25)])
    assert not _has_char_ink(img, 0, 180, 10, 50)


def test_faint_rows_not_char_ink():
    """墨率不够的行不算——扫描噪点常连成一片但很淡。"""
    img = _page([(20, 40, 0.05)])
    assert not _has_char_ink(img, 0, 180, 10, 50)


def test_empty_band_is_safe():
    assert not _has_char_ink(_page([]), 0, 180, 10, 50)
    assert not _has_char_ink(_page([]), 0, 180, 50, 10)   # 反向区间
    assert not _has_char_ink(_page([]), 0, 0, 10, 50)     # 空宽度


def test_thresholds_are_sane():
    """闸值本身的护栏：放太松则框墨进来，放太紧则继续切字。"""
    assert 0 < PIN_INK_ROW_T < 0.5, "行墨率闸离谱"
    assert 2 <= PIN_INK_RUN <= 8, "连续行数闸离谱"
    assert 0 < FRAME_BAND_MAX_CUT < 0.5


def test_real_page_tight_boxes_do_not_clip_char_tops(tmp_path, monkeypatch, ws,
                                                    fixture_page):
    """真页端到端：紧框上方不该再有成段字墨（钉桩不许吞字）。

    2026-09-20 改：原先这条按 `(page, col, slot)` 点名 vol01 的五个格位——
    那五个是人裁标过 truncated 的实例，靶子精准，但**产物在工作区**，云端
    一条都跑不了，本机重跑一次参数不同也可能整条 skip（原实现里四个
    `pytest.skip` 分支就是为此而设）。

    现在改成拿 `tests/fixtures/` 里那张冻结真页从 Step1 跑到 Step4，对**每一个**
    切出来的字格查同一条不变量。样本换了（不再是那五个原始靶位），但判据一字
    没动，而且覆盖面反而大得多：一页八列、一百二十多个字格，每次都真的执行。

    原始五个靶位的结论（修复后 R4 从 0.51% 降到 0.05%）留在模块头，
    要复现就跑评测：`guji eval run`（R4 那把尺子在 `eval/rulers.py`）。
    """
    import cv2

    import open_guji_cv.steps  # noqa: F401  —— 注册产物种类与步骤
    from helpers import run_keben_from_raw
    from open_guji_cv.core.book import load_book

    ctx, out = run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"),
                                  gray=fixture_page)
    cells = {c.col: c for c in out["cells"].columns}
    chars = {c.col: c for c in out["char_index"].columns}
    assert cells and chars, "冻结样页跑完 Step4 却没有产物——链路断了"

    checked = 0
    for col, cic in chars.items():
        img = cv2.imread(str(ctx.cache.get(ctx.book.id, "column_image",
                                           f"p0001c{col:02d}")),
                         cv2.IMREAD_GRAYSCALE)
        assert img is not None, f"c{col} 列图没落缓存"
        by_slot = {x.slot: x for x in cells[col].cells}
        for ch in cic.chars:
            cell = by_slot.get(getattr(ch, "slot", None))
            if cell is None:
                continue
            above = (img < 128)[int(cell.y0):int(ch.bbox_col[1])]
            if above.size == 0:
                continue
            checked += 1
            rows = above.mean(axis=1) > 0.05
            run = best = 0
            for v in rows:
                run = run + 1 if v else 0
                best = max(best, run)
            assert best < 6, \
                f"c{col}s{ch.slot} 紧框上方仍有 {best} 行成段字墨（又切字顶了）"
    assert checked > 50, f"只查到 {checked} 个字格，样本太少，这条用例形同虚设"
